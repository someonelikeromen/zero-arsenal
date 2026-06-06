/**
 * HomePage — 首页枢纽，左侧竖向导航 + 七 Tab 布局
 * 会话 / 世界 / 人物 / 资产库 / 存档 / 提示词 / 设置
 */
import React, { useEffect, useState } from 'react'
import { api, World, CharacterTemplate } from '../lib/api'
import { WorldManager } from '../components/WorldManager'
import { CharacterCreator } from '../components/CharacterCreator'
import { AssetLibrary } from '../components/AssetLibrary'
import { SessionManager } from '../components/SessionManager'
import { PromptManager } from '../components/PromptManager'
import { SettingsPage } from './SettingsPage'
import ScraperRulesPanel from '../components/ScraperRulesPanel'
import ExtensionsPanel from '../components/ExtensionsPanel'
import { LlmConfigBanner } from '../components/LlmConfigBanner'
import { ThemeGuideModal, shouldShowThemeGuide } from '../components/ThemeGuideModal'
import { notify } from '../stores/ui'

const LS_WORLD = 'za_last_world_id'
const LS_CHAR = 'za_last_char_id'

interface Props {
  onSelectSession: (id: string) => void
}

type TabId = 'sessions' | 'worlds' | 'characters' | 'assets' | 'prompts' | 'extensions' | 'settings'

const NAV_ITEMS: { id: TabId; icon: string; label: string }[] = [
  { id: 'sessions',   icon: '🎮', label: '会话' },
  { id: 'worlds',     icon: '🌍', label: '世界' },
  { id: 'characters', icon: '👤', label: '人物' },
  { id: 'assets',     icon: '🎒', label: '资产库' },
  { id: 'prompts',    icon: '📝', label: '提示词' },
  { id: 'extensions', icon: '🧩', label: '插件' },
  { id: 'settings',   icon: '⚙️', label: '设置' },
]

// ── 会话 Tab（P0-5：合并「新建会话」与「会话存档列表」于同一 Tab）─────────────
function SessionsTab({ onSelectSession, onNavigate }: {
  onSelectSession: (id: string) => void
  onNavigate: (tab: TabId) => void
}) {
  const [worlds, setWorlds] = useState<World[]>([])
  const [characters, setCharacters] = useState<CharacterTemplate[]>([])
  const [title, setTitle] = useState('')
  const [worldPlugin, setWorldPlugin] = useState('crossover')
  const [selectedWorldId, setSelectedWorldId] = useState('')
  const [selectedCharId, setSelectedCharId] = useState('')
  const [creating, setCreating] = useState(false)
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    api.listWorlds().then(r => {
      setWorlds(r.worlds)
      // 最近使用默认（localStorage）
      const last = localStorage.getItem(LS_WORLD)
      if (last && r.worlds.some(w => w.id === last)) setSelectedWorldId(last)
    }).catch(() => {})
    api.listCharacterTemplates().then(r => {
      setCharacters(r.characters)
      const last = localStorage.getItem(LS_CHAR)
      if (last && r.characters.some(c => c.id === last)) setSelectedCharId(last)
    }).catch(() => {})
  }, [])

  // 插件（plugin_key）与世界（world_id）独立选择，互不影响

  const handleCreate = async () => {
    setCreating(true)
    try {
      const res = await api.createSession({
        plugin_key: worldPlugin,
        title: title || undefined,
        world_id: selectedWorldId || undefined,
        character_template_id: selectedCharId || undefined,
      })
      if (selectedWorldId) localStorage.setItem(LS_WORLD, selectedWorldId)
      if (selectedCharId) localStorage.setItem(LS_CHAR, selectedCharId)
      onSelectSession((res as { session_id: string }).session_id)
    } catch (e: unknown) {
      notify.error(`创建失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setCreating(false)
    }
  }

  const WORLD_PLUGINS = ['crossover', 'wuxia', 'infinite_arsenal', 'muv_luv', 'gundam_seed']

  return (
    <div className="max-w-3xl mx-auto space-y-6 pt-2">
      {/* 顶部：新建会话（默认折叠，点击展开组合开局） */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">会话</h2>
          <p className="text-sm text-zinc-500">在此新建会话或打开已有存档</p>
        </div>
        <button onClick={() => setShowCreate(v => !v)}
          className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-1.5 rounded text-sm font-medium transition-colors">
          {showCreate ? '收起' : '+ 新建会话'}
        </button>
      </div>

      {showCreate && (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-5">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">会话标题（可选）</label>
            <input value={title} onChange={e => setTitle(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-500 placeholder-zinc-600"
              placeholder="自动生成标题" />
          </div>
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">世界插件</label>
            <select value={worldPlugin} onChange={e => setWorldPlugin(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-500">
              {WORLD_PLUGINS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
        </div>

        {/* 世界选择器：卡片预览 */}
        <div>
          <label className="text-xs text-zinc-400 mb-2 block">世界模板</label>
          {worlds.length === 0 ? (
            <div className="border border-dashed border-zinc-700 rounded p-4 text-center">
              <p className="text-xs text-zinc-500 mb-1">还没有世界模板</p>
              <button onClick={() => onNavigate('worlds')} className="text-indigo-400 hover:text-indigo-300 text-sm">
                → 先去创建世界
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2 max-h-44 overflow-y-auto pr-1">
              <button onClick={() => setSelectedWorldId('')}
                className={`text-left rounded border p-2.5 ${selectedWorldId === '' ? 'border-indigo-500 bg-indigo-600/10' : 'border-zinc-700 hover:border-zinc-500'}`}>
                <div className="text-sm font-medium">不使用世界模板</div>
                <div className="text-xs text-zinc-500">仅用插件默认设定开局</div>
              </button>
              {worlds.map(w => (
                <button key={w.id} onClick={() => setSelectedWorldId(w.id)}
                  className={`text-left rounded border p-2.5 ${selectedWorldId === w.id ? 'border-indigo-500 bg-indigo-600/10' : 'border-zinc-700 hover:border-zinc-500'}`}>
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-medium truncate">{w.name}</span>
                    <span className="text-[10px] bg-zinc-700 text-zinc-400 px-1 rounded shrink-0">{w.plugin_key}</span>
                  </div>
                  <div className="text-xs text-zinc-500 line-clamp-2 mt-0.5">{w.description || '（无描述）'}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 人物选择器：卡片预览 */}
        <div>
          <label className="text-xs text-zinc-400 mb-2 block">人物模板</label>
          {characters.length === 0 ? (
            <div className="border border-dashed border-zinc-700 rounded p-4 text-center">
              <p className="text-xs text-zinc-500 mb-1">还没有人物模板</p>
              <button onClick={() => onNavigate('characters')} className="text-indigo-400 hover:text-indigo-300 text-sm">
                → 先去创建人物
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2 max-h-44 overflow-y-auto pr-1">
              <button onClick={() => setSelectedCharId('')}
                className={`text-left rounded border p-2.5 ${selectedCharId === '' ? 'border-indigo-500 bg-indigo-600/10' : 'border-zinc-700 hover:border-zinc-500'}`}>
                <div className="text-sm font-medium">使用默认角色</div>
                <div className="text-xs text-zinc-500">系统生成基础角色卡</div>
              </button>
              {characters.map(c => (
                <button key={c.id} onClick={() => setSelectedCharId(c.id)}
                  className={`text-left rounded border p-2.5 ${selectedCharId === c.id ? 'border-indigo-500 bg-indigo-600/10' : 'border-zinc-700 hover:border-zinc-500'}`}>
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-medium truncate">{c.name}</span>
                    <span className="text-[10px] bg-zinc-700 text-zinc-400 px-1 rounded shrink-0">{c.plugin_key}</span>
                  </div>
                  <div className="text-xs text-zinc-500 mt-0.5">更新于 {new Date((c.updated_at || 0) * 1000).toLocaleDateString()}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        <button onClick={handleCreate} disabled={creating}
          className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white py-2.5 rounded text-sm font-medium transition-colors">
          {creating ? '创建中...' : '开始会话'}
        </button>
      </div>
      )}

      {/* 会话存档列表（原「存档」Tab 合并至此） */}
      <SessionManager onOpenSession={onSelectSession} />
    </div>
  )
}

// ── 设置 Tab ──────────────────────────────────────────────────────────────────
type SettingsSection = 'general' | 'scraper'

function SettingsTab() {
  const [section, setSection] = useState<SettingsSection>('general')

  return (
    <div className="flex gap-6 h-full">
      {/* 左侧小导航 */}
      <div className="w-40 shrink-0 space-y-1 pt-1">
        {([
          { id: 'general' as const, label: '常规设置', icon: '⚙️' },
          { id: 'scraper' as const, label: '站点抓取', icon: '🌐' },
        ]).map(s => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            className={`w-full flex items-center gap-2 px-3 py-2 rounded text-sm transition-colors ${
              section === s.id
                ? 'bg-indigo-600/20 text-indigo-300'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
            }`}
          >
            <span>{s.icon}</span>
            <span>{s.label}</span>
          </button>
        ))}
      </div>

      {/* 右侧内容 */}
      <div className="flex-1 min-w-0">
        {section === 'general' && <SettingsPage embedded={true} />}
        {section === 'scraper' && <ScraperRulesPanel />}
      </div>
    </div>
  )
}

// ── 主组件 ────────────────────────────────────────────────────────────────────
export const HomePage: React.FC<Props> = ({ onSelectSession }) => {
  const [activeTab, setActiveTab] = useState<TabId>('sessions')
  const [collapsed, setCollapsed] = useState(false)
  const [showThemeGuide, setShowThemeGuide] = useState(() => shouldShowThemeGuide())

  const renderContent = () => {
    switch (activeTab) {
      case 'sessions':
        return <SessionsTab onSelectSession={onSelectSession} onNavigate={setActiveTab} />
      case 'worlds':
        return <WorldManager />
      case 'characters':
        return <CharacterCreator />
      case 'assets':
        return <AssetLibrary />
      case 'prompts':
        return <PromptManager />
      case 'extensions':
        return <ExtensionsPanel />
      case 'settings':
        return <SettingsTab />
      default:
        return null
    }
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex">
      {showThemeGuide && <ThemeGuideModal onClose={() => setShowThemeGuide(false)} />}
      {/* 左侧导航栏 */}
      <div className={`flex flex-col shrink-0 bg-zinc-900 border-r border-zinc-800 transition-all duration-200 ${collapsed ? 'w-14' : 'w-44'}`}>
        {/* Logo 区 */}
        <div className="flex items-center gap-2 px-3 py-4 border-b border-zinc-800">
          {!collapsed && (
            <div>
              <div className="font-bold text-sm">零度武库</div>
              <div className="text-xs text-zinc-600">ZeroArsenal</div>
            </div>
          )}
          <button onClick={() => setCollapsed(!collapsed)}
            className={`ml-auto text-zinc-600 hover:text-zinc-400 text-sm ${collapsed ? 'mx-auto' : ''}`}>
            {collapsed ? '→' : '←'}
          </button>
        </div>

        {/* 导航项 */}
        <nav className="flex-1 py-2">
          {NAV_ITEMS.map(item => (
            <button key={item.id} onClick={() => setActiveTab(item.id)}
              title={collapsed ? item.label : undefined}
              className={`w-full flex items-center gap-3 px-3 py-2.5 text-sm transition-colors ${
                activeTab === item.id
                  ? 'bg-indigo-600/20 text-indigo-300 border-r-2 border-indigo-500'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
              }`}>
              <span className="text-base shrink-0">{item.icon}</span>
              {!collapsed && <span>{item.label}</span>}
            </button>
          ))}
        </nav>

        {/* 底部版本 */}
        {!collapsed && (
          <div className="px-3 py-3 border-t border-zinc-800">
            <p className="text-xs text-zinc-700">v0.1 · TRPG Tool</p>
          </div>
        )}
      </div>

      {/* 右侧内容区 */}
      <div className="flex-1 min-w-0 overflow-hidden flex flex-col">
        {/* 页面标题栏 */}
        <div className="flex items-center gap-2 px-6 py-3 border-b border-zinc-800 shrink-0">
          <span className="text-base">{NAV_ITEMS.find(n => n.id === activeTab)?.icon}</span>
          <h1 className="font-semibold">{NAV_ITEMS.find(n => n.id === activeTab)?.label}</h1>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="mb-3">
            <LlmConfigBanner onGoSettings={() => setActiveTab('settings')} />
          </div>
          {renderContent()}
        </div>
      </div>
    </div>
  )
}
