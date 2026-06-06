/**
 * CharacterCreator — 全局人物模板管理 + 5步向导创建
 * 三种模式：快速 / 问卷 / 背景描述
 * SSE 流式预览，支持手动编辑和重新生成
 */
import React, { useEffect, useState } from 'react'
import { api, CharacterTemplate } from '../lib/api'
import { notify } from '../stores/ui'
import { requestConfirm } from '../stores/confirm'
import { CharacterEditor } from './CharacterEditor'

// ── 类型 ──────────────────────────────────────────────────────────────────────
type CreateMode = 'quick' | 'quiz' | 'background'
type WizardStep = 0 | 1 | 2 | 3 | 4

interface Question { id: string; question: string; options: Record<string, string> }
interface QuizAnswer { question: string; answer: string }

// ── 步骤 0：选择创建模式 ──────────────────────────────────────────────────────
function StepMode({ onSelect }: { onSelect: (m: CreateMode) => void }) {
  const modes: { id: CreateMode; icon: string; label: string; desc: string }[] = [
    { id: 'quick', icon: '⚡', label: '快速创建', desc: '填写基础信息，AI 直接生成' },
    { id: 'quiz', icon: '📋', label: '问卷创建', desc: 'AI 出 5 道情境题，根据作答生成角色' },
    { id: 'background', icon: '📖', label: '背景创建', desc: '粘贴角色背景文本，AI 解析生成' },
  ]
  return (
    <div className="space-y-3">
      <p className="text-sm text-zinc-400">选择创建方式</p>
      {modes.map(m => (
        <button key={m.id} onClick={() => onSelect(m.id)}
          className="w-full text-left bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 hover:border-indigo-500 rounded-lg p-4 transition-colors">
          <div className="flex items-center gap-3">
            <span className="text-xl">{m.icon}</span>
            <div>
              <div className="font-medium text-sm">{m.label}</div>
              <div className="text-xs text-zinc-500 mt-0.5">{m.desc}</div>
            </div>
          </div>
        </button>
      ))}
    </div>
  )
}

// ── 创建向导 Modal ────────────────────────────────────────────────────────────
function CreatorModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [step, setStep] = useState<WizardStep>(0)
  const [mode, setMode] = useState<CreateMode>('quick')
  const [name, setName] = useState('')
  const [gender, setGender] = useState('')
  const [worldPlugin, setWorldPlugin] = useState('crossover')
  const [charType, setCharType] = useState<'original' | 'transmigrator'>('original')
  const [traversal, setTraversal] = useState('')
  const [background, setBackground] = useState('')
  // Phase 2A 高度自定义入口
  const [coreTraits, setCoreTraits] = useState('')
  const [abilityTendency, setAbilityTendency] = useState('mixed')
  const [canonSource, setCanonSource] = useState('')
  const [firstMessage, setFirstMessage] = useState('')
  const [questions, setQuestions] = useState<Question[]>([])
  const [answers, setAnswers] = useState<QuizAnswer[]>([])
  const [currentQIdx, setCurrentQIdx] = useState(0)
  const [selectedOption, setSelectedOption] = useState('')
  const [generating, setGenerating] = useState(false)
  const [charData, setCharData] = useState<Record<string, unknown> | null>(null)
  const [sseLog, setSseLog] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const goStep = (s: WizardStep) => { setStep(s); setError('') }

  // 步骤2: 问卷模式 — 获取题目
  const loadQuestions = async () => {
    setGenerating(true)
    setError('')
    try {
      const resp = await fetch('/api/characters/generate/questions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_key: worldPlugin, char_type: charType }),
      })
      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          try {
            const evt = JSON.parse(line.slice(5).trim())
            if (evt.type === 'done' && evt.questions) {
              setQuestions(evt.questions)
              setAnswers([])
              setCurrentQIdx(0)
            }
          } catch { /* ignore */ }
        }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '获取题目失败')
    } finally {
      setGenerating(false)
    }
  }

  const handleStep1Next = () => {
    if (!name) { setError('请填写角色名称'); return }
    if (mode === 'quiz') {
      goStep(2)
      loadQuestions()
    } else {
      goStep(2)
    }
  }

  const handleAnswerQuestion = () => {
    if (!selectedOption) return
    const q = questions[currentQIdx]
    const ans = { question: q.question, answer: `${selectedOption}: ${q.options[selectedOption]}` }
    const newAnswers = [...answers, ans]
    setAnswers(newAnswers)
    if (currentQIdx < questions.length - 1) {
      setCurrentQIdx(prev => prev + 1)
      setSelectedOption('')
    } else {
      // All answered, go generate
      goStep(3)
      generateCharacter(newAnswers)
    }
  }

  // 步骤3: 生成角色
  const generateCharacter = async (quizAnswers?: QuizAnswer[]) => {
    setGenerating(true)
    setSseLog('生成中...')
    setCharData(null)
    setError('')
    try {
      const body = {
        mode,
        plugin_key: worldPlugin,
        name,
        gender,
        char_type: charType,
        traversal_method: traversal,
        background_text: background,
        answers: quizAnswers || answers,
        core_traits: coreTraits,
        ability_tendency: abilityTendency,
        canon_source: canonSource,
        first_message: firstMessage,
      }
      const resp = await fetch('/api/characters/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          try {
            const evt = JSON.parse(line.slice(5).trim())
            if (evt.type === 'done') { setCharData(evt.character); setSseLog('生成完成'); goStep(4) }
            if (evt.type === 'error') { setError(evt.message); setSseLog('') }
          } catch { /* ignore */ }
        }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  const handleRegenerate = () => {
    goStep(3)
    generateCharacter()
  }

  const handleSave = async () => {
    if (!charData) return
    setSaving(true)
    try {
      await api.createCharacterTemplate({ name: (charData.name as string) || name, plugin_key: worldPlugin, data_json: charData })
      notify.success('已保存为人物模板')
      onSaved()
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败')
      notify.error(`保存失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  const STEP_LABELS = ['选模式', '基础信息', mode === 'quiz' ? '问卷' : '详细', '生成中', '预览确认']

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* 步骤指示 */}
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <div className="flex gap-1">
            {STEP_LABELS.map((label, i) => (
              <div key={i} className={`flex items-center gap-1 ${i > 0 ? 'ml-1' : ''}`}>
                {i > 0 && <span className="text-zinc-700 text-xs">›</span>}
                <span className={`text-xs px-2 py-0.5 rounded-full ${i === step
                  ? 'bg-indigo-600 text-white' : i < step
                    ? 'bg-zinc-700 text-zinc-300' : 'text-zinc-600'}`}>
                  {label}
                </span>
              </div>
            ))}
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">×</button>
        </div>

        <div className="p-4 space-y-4">
          {error && <div className="bg-red-900/30 border border-red-700 rounded p-2 text-xs text-red-300">{error}</div>}

          {/* Step 0: 选模式 */}
          {step === 0 && (
            <StepMode onSelect={m => { setMode(m); goStep(1) }} />
          )}

          {/* Step 1: 基础信息 */}
          {step === 1 && (
            <div className="space-y-3">
              <p className="text-xs text-zinc-500">模式：{mode === 'quick' ? '快速创建' : mode === 'quiz' ? '问卷创建' : '背景创建'}</p>
              <input value={name} onChange={e => setName(e.target.value)}
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
                placeholder="角色名称（必填）" />
              <div className="flex gap-2">
                <input value={gender} onChange={e => setGender(e.target.value)}
                  className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none"
                  placeholder="性别（可选）" />
                <select value={worldPlugin} onChange={e => setWorldPlugin(e.target.value)}
                  className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none">
                  {['crossover', 'wuxia', 'infinite_arsenal', 'muv_luv', 'gundam_seed'].map(p => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              </div>
              <div className="flex gap-2">
                <button onClick={() => setCharType('original')}
                  className={`flex-1 py-1.5 rounded text-xs border ${charType === 'original' ? 'border-indigo-500 bg-indigo-600/20 text-indigo-300' : 'border-zinc-700 text-zinc-400'}`}>
                  原创角色
                </button>
                <button onClick={() => setCharType('transmigrator')}
                  className={`flex-1 py-1.5 rounded text-xs border ${charType === 'transmigrator' ? 'border-indigo-500 bg-indigo-600/20 text-indigo-300' : 'border-zinc-700 text-zinc-400'}`}>
                  穿越者
                </button>
              </div>
              {charType === 'transmigrator' && (
                <input value={traversal} onChange={e => setTraversal(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none"
                  placeholder="穿越方式（可选，如：意外穿越/书穿/魂穿）" />
              )}

              {/* 高度自定义入口 */}
              <div className="space-y-2 border-t border-zinc-800 pt-3">
                <div>
                  <label className="text-xs text-zinc-400 flex items-center gap-1">
                    核心特质关键词
                    <span className="text-zinc-600" title="2-3 个描述性格内核的词，AI 会据此构建 psyche_model.core_values">ⓘ</span>
                  </label>
                  <textarea value={coreTraits} onChange={e => setCoreTraits(e.target.value)} rows={2}
                    className="w-full mt-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none resize-none"
                    placeholder="如：冷漠、精准、前军人（可选，但能让角色更贴合你的设想）" />
                </div>
                <div>
                  <label className="text-xs text-zinc-400 flex items-center gap-1">
                    能力倾向
                    <span className="text-zinc-600" title="影响 capability_cap 权重，避免各项能力平均堆高">ⓘ</span>
                  </label>
                  <div className="flex gap-1 mt-1">
                    {([['combat','战斗型'],['tech','技术型'],['social','社交型'],['mixed','混合型']] as const).map(([v, label]) => (
                      <button key={v} onClick={() => setAbilityTendency(v)}
                        className={`flex-1 py-1.5 rounded text-xs border ${abilityTendency === v ? 'border-indigo-500 bg-indigo-600/20 text-indigo-300' : 'border-zinc-700 text-zinc-400'}`}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="text-xs text-zinc-400 flex items-center gap-1">
                    原作来源（可选）
                    <span className="text-zinc-600" title="填原作角色名让 AI 参考其设定；或填资料 URL，后端会联网抓取作为上下文">ⓘ</span>
                  </label>
                  <input value={canonSource} onChange={e => setCanonSource(e.target.value)}
                    className="w-full mt-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none"
                    placeholder="原作角色名 或 资料 URL（如 wiki 链接）" />
                </div>
                <div>
                  <label className="text-xs text-zinc-400 flex items-center gap-1">
                    开场独白 first_message（可选）
                    <span className="text-zinc-600" title="角色登场时的第一句话/独白，会原样写入档案用于开场叙事">ⓘ</span>
                  </label>
                  <textarea value={firstMessage} onChange={e => setFirstMessage(e.target.value)} rows={2}
                    className="w-full mt-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none resize-none"
                    placeholder="如：「又是无聊的一天……」他靠在椅背上，目光扫过门口。" />
                </div>
              </div>

              {mode === 'background' && (
                <textarea value={background} onChange={e => setBackground(e.target.value)} rows={5}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none resize-none"
                  placeholder="粘贴角色背景故事、设定描述..." />
              )}
              <div className="flex gap-2">
                <button onClick={() => goStep(0)} className="px-4 py-2 rounded text-sm text-zinc-400 hover:text-zinc-200">← 返回</button>
                <button onClick={handleStep1Next}
                  className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white py-2 rounded text-sm">
                  {mode === 'quick' ? '生成' : mode === 'quiz' ? '开始问卷' : '生成角色'}
                </button>
              </div>
            </div>
          )}

          {/* Step 2: 问卷模式 — 答题 */}
          {step === 2 && mode === 'quiz' && (
            <div className="space-y-4">
              {generating ? (
                <div className="text-center text-zinc-500 text-sm py-6">生成问题中...</div>
              ) : questions.length > 0 ? (
                <>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-zinc-400">问题 {currentQIdx + 1} / {questions.length}</span>
                    <div className="flex gap-1">
                      {questions.map((_, i) => (
                        <div key={i} className={`w-2 h-2 rounded-full ${i < answers.length ? 'bg-indigo-500' : i === currentQIdx ? 'bg-indigo-300' : 'bg-zinc-700'}`} />
                      ))}
                    </div>
                  </div>
                  <p className="text-sm font-medium leading-relaxed">{questions[currentQIdx]?.question}</p>
                  <div className="space-y-2">
                    {Object.entries(questions[currentQIdx]?.options || {}).map(([k, v]) => (
                      <button key={k} onClick={() => setSelectedOption(k)}
                        className={`w-full text-left rounded p-3 text-sm border transition-colors ${selectedOption === k
                          ? 'border-indigo-500 bg-indigo-600/20 text-indigo-200' : 'border-zinc-700 bg-zinc-800 hover:border-zinc-500'}`}>
                        <span className="font-bold mr-2">{k}.</span>{v}
                      </button>
                    ))}
                  </div>
                  <button onClick={handleAnswerQuestion} disabled={!selectedOption}
                    className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white py-2 rounded text-sm">
                    {currentQIdx < questions.length - 1 ? '下一题' : '生成角色'}
                  </button>
                </>
              ) : null}
            </div>
          )}

          {/* Step 2: 其他模式（背景/快速）— 直接进步骤3时过渡 */}
          {step === 2 && mode !== 'quiz' && (
            <div className="text-center text-zinc-500 text-sm py-6">
              {generating ? '准备生成...' : (
                <button onClick={() => { goStep(3); generateCharacter() }}
                  className="bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-2 rounded text-sm">
                  开始生成
                </button>
              )}
            </div>
          )}

          {/* Step 3: 生成中 */}
          {step === 3 && (
            <div className="text-center py-8 space-y-3">
              <div className="text-3xl animate-pulse">⚙️</div>
              <p className="text-sm text-zinc-300">{sseLog || '角色生成中...'}</p>
              {error && <p className="text-xs text-red-400">{error}</p>}
            </div>
          )}

          {/* Step 4: 预览 + 结构化编辑 */}
          {step === 4 && charData && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-xs text-zinc-500">生成完成，可在此微调任意字段后保存</p>
                <span className="text-xs bg-zinc-700 text-zinc-400 px-2 py-0.5 rounded">{charData.plugin_key as string}</span>
              </div>

              <CharacterEditor data={charData} onChange={setCharData} />

              <div className="flex gap-2 pt-2">
                <button onClick={handleRegenerate} disabled={generating}
                  className="flex-1 border border-zinc-600 hover:border-zinc-400 text-zinc-300 py-2 rounded text-sm disabled:opacity-50">
                  {generating ? '生成中...' : '重新生成'}
                </button>
                <button onClick={handleSave} disabled={saving}
                  className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white py-2 rounded text-sm">
                  {saving ? '保存中...' : '保存为模板'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── 模板编辑 Modal（复用 CharacterEditor）─────────────────────────────────────
function EditModal({ cid, onClose, onSaved }: { cid: string; onClose: () => void; onSaved: () => void }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [name, setName] = useState('')
  const [worldPlugin, setWorldPlugin] = useState('crossover')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    (async () => {
      try {
        const res = await api.getCharacterTemplate(cid)
        setData(res.data_json || {})
        setName(res.name)
        setWorldPlugin(res.plugin_key)
      } catch (e) {
        notify.error(`加载模板失败：${e instanceof Error ? e.message : String(e)}`)
        onClose()
      } finally {
        setLoading(false)
      }
    })()
  }, [cid, onClose])

  const save = async () => {
    if (!data) return
    setSaving(true)
    try {
      await api.updateCharacterTemplate(cid, { name: (data.name as string) || name, plugin_key: worldPlugin, data_json: data })
      notify.success('已保存模板修改')
      onSaved()
      onClose()
    } catch (e) {
      notify.error(`保存失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <h3 className="font-semibold">编辑人物模板</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">×</button>
        </div>
        <div className="p-4">
          {loading ? (
            <div className="text-center text-zinc-500 text-sm py-8">加载中...</div>
          ) : data ? (
            <div className="space-y-4">
              <CharacterEditor data={data} onChange={setData} />
              <button onClick={save} disabled={saving}
                className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white py-2 rounded text-sm">
                {saving ? '保存中...' : '保存修改'}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

// ── 人物卡片列表 ──────────────────────────────────────────────────────────────
function CharacterCard({ char, onEdit, onClone, onDelete }: {
  char: CharacterTemplate; onEdit: () => void; onClone: () => void; onDelete: () => void
}) {
  return (
    <div className="bg-zinc-800 border border-zinc-700 rounded-lg px-4 py-3 flex items-center gap-3 group cursor-pointer hover:border-zinc-600"
      onClick={onEdit}>
      <div className="w-8 h-8 bg-indigo-600/20 rounded-full flex items-center justify-center text-sm">
        {char.name.slice(0, 1)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm">{char.name}</span>
          <span className="text-xs bg-zinc-700 text-zinc-400 px-1.5 py-0.5 rounded">{char.plugin_key}</span>
        </div>
        <p className="text-xs text-zinc-500 mt-0.5">
          更新于 {new Date((char.updated_at || 0) * 1000).toLocaleDateString()}
        </p>
      </div>
      <div className="flex gap-2 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
        <a href={api.exportCharacterPngUrl(char.id)} download
          className="text-xs text-zinc-400 hover:text-zinc-200" title="导出为 PNG 角色卡">导出</a>
        <button onClick={onClone} className="text-xs text-zinc-400 hover:text-zinc-200">克隆</button>
        <button onClick={onDelete} className="text-xs text-red-500 hover:text-red-400">删除</button>
      </div>
    </div>
  )
}

// ── 主组件 ────────────────────────────────────────────────────────────────────
export const CharacterCreator: React.FC = () => {
  const [characters, setCharacters] = useState<CharacterTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const fileRef = React.useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.listCharacterTemplates()
      setCharacters(res.characters)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleDelete = async (cid: string) => {
    const ok = await requestConfirm({
      title: '删除人物模板',
      message: '确认删除该人物模板？此操作不可撤销。',
      confirmText: '删除',
      danger: true,
    })
    if (!ok) return
    try {
      await api.deleteCharacterTemplate(cid)
      notify.success('已删除人物模板')
      load()
    } catch (e) {
      notify.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleClone = async (char: CharacterTemplate) => {
    try {
      const full = await api.getCharacterTemplate(char.id)
      const data = { ...(full.data_json || {}) }
      const cloneName = `${char.name}_副本`
      data.name = cloneName
      await api.createCharacterTemplate({ name: cloneName, plugin_key: char.plugin_key, data_json: data })
      notify.success(`已克隆为「${cloneName}」`)
      load()
    } catch (e) {
      notify.error(`克隆失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleImportPng = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const res = await api.importCharacterPng(file)
      notify.success(`已导入角色「${res.name}」`)
      load()
    } catch (err) {
      notify.error(`导入失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-32 text-zinc-500 text-sm">加载中...</div>
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">人物库</h2>
        <div className="flex gap-2">
          <input ref={fileRef} type="file" accept="image/png" className="hidden" onChange={handleImportPng} />
          <button onClick={() => fileRef.current?.click()}
            className="border border-zinc-600 hover:border-zinc-400 text-zinc-300 px-3 py-1.5 rounded text-sm"
            title="导入 SillyTavern / Chub PNG 角色卡">
            导入 PNG
          </button>
          <button onClick={() => setShowModal(true)}
            className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-1.5 rounded text-sm">
            + 创建人物
          </button>
        </div>
      </div>

      {characters.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-zinc-500 gap-3">
          <p className="text-sm">暂无人物模板</p>
          <button onClick={() => setShowModal(true)} className="text-indigo-400 hover:text-indigo-300 text-sm">
            创建第一个人物 →
          </button>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
          {characters.map(c => (
            <CharacterCard key={c.id} char={c}
              onEdit={() => setEditId(c.id)}
              onClone={() => handleClone(c)}
              onDelete={() => handleDelete(c.id)} />
          ))}
        </div>
      )}

      {showModal && (
        <CreatorModal onClose={() => setShowModal(false)} onSaved={load} />
      )}
      {editId && (
        <EditModal cid={editId} onClose={() => setEditId(null)} onSaved={load} />
      )}
    </div>
  )
}
