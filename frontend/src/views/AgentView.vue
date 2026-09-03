<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { apiClient, errorMessage } from '../api'
import { useMarketStore } from '../stores/market'
import type { AgentSource } from '../types'

type ChatRole = 'user' | 'assistant'
interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  sources?: AgentSource[]
  isGreeting?: boolean
}
interface Conversation {
  id: string
  title: string
  updatedAt: number
  messages: ChatMessage[]
}

const STORAGE_KEY = 'price-radar-agent-conversations-v1'
const market = useMarketStore()
const question = ref('')
const asking = ref(false)
const conversation = ref<HTMLElement | null>(null)

function createId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function createConversation(): Conversation {
  return {
    id: createId(),
    title: '新行情问答',
    updatedAt: Date.now(),
    messages: [{
      id: createId(),
      role: 'assistant',
      isGreeting: true,
      content: '我是你的行情问答助手。你可以直接问某个型号的价格、今天哪些机型涨跌最多，或查看异常波动。我会先查询已发布报价，再给你答案。',
    }],
  }
}

function loadConversations(): Conversation[] {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    if (Array.isArray(saved) && saved.length) return saved as Conversation[]
  } catch {
    // 保存记录损坏时自动新建，不影响行情问答。
  }
  return [createConversation()]
}

const conversations = ref<Conversation[]>(loadConversations())
const activeConversationId = ref(conversations.value[0].id)
const activeConversation = computed(() => conversations.value.find(item => item.id === activeConversationId.value) || conversations.value[0])
const messages = computed(() => activeConversation.value.messages)
const suggestedQuestions = [
  '今天整体行情怎么样？',
  '今天跌得最多的 5 个型号有哪些？',
  '有哪些涨跌超过 500 元的异常报价？',
  '查一下红米 K80 的最新报价',
]

const history = computed(() => messages.value
  .filter(message => !message.isGreeting)
  .slice(-10)
  .map(message => ({ role: message.role, content: message.content })))

function persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.value.slice(0, 30)))
}

function touchCurrent() {
  activeConversation.value.updatedAt = Date.now()
  conversations.value.sort((a, b) => b.updatedAt - a.updatedAt)
  persist()
}

function appendMessage(message: Omit<ChatMessage, 'id'>) {
  activeConversation.value.messages.push({ id: createId(), ...message })
  touchCurrent()
}

function newConversation() {
  if (asking.value) return
  const item = createConversation()
  conversations.value.unshift(item)
  activeConversationId.value = item.id
  question.value = ''
  persist()
  scrollToBottom()
}

function selectConversation(id: string) {
  if (asking.value) return
  activeConversationId.value = id
  scrollToBottom()
}

function removeConversation(id: string) {
  if (asking.value) return
  conversations.value = conversations.value.filter(item => item.id !== id)
  if (!conversations.value.length) conversations.value = [createConversation()]
  if (activeConversationId.value === id) activeConversationId.value = conversations.value[0].id
  persist()
}

function preview(item: Conversation) {
  const latest = item.messages.at(-1)?.content || '等待提问'
  return latest.replace(/\s+/g, ' ').slice(0, 28)
}

function recordTime(value: number) {
  const time = new Date(value)
  const today = new Date()
  if (time.toDateString() === today.toDateString()) return time.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return `${time.getMonth() + 1}/${time.getDate()}`
}

async function scrollToBottom() {
  await nextTick()
  conversation.value?.scrollTo({ top: conversation.value.scrollHeight, behavior: 'smooth' })
}

async function ask(value = question.value) {
  const content = value.trim()
  if (!content || asking.value) return
  const threadId = activeConversation.value.id
  const previousHistory = history.value
  appendMessage({ role: 'user', content })
  if (activeConversation.value.title === '新行情问答') {
    activeConversation.value.title = content.slice(0, 18)
    persist()
  }
  question.value = ''
  asking.value = true
  await scrollToBottom()
  try {
    const result = await apiClient.askAgent(content, previousHistory)
    if (activeConversationId.value === threadId) appendMessage({ role: 'assistant', content: result.answer, sources: result.sources })
  } catch (error) {
    if (activeConversationId.value === threadId) appendMessage({
      role: 'assistant',
      content: `暂时无法完成查询：${errorMessage(error)}。请确认 Ollama 正在运行，再重试。`,
    })
  } finally {
    asking.value = false
    await scrollToBottom()
  }
}

onMounted(scrollToBottom)
</script>

<template>
  <section class="view-panel agent-view">
    <div class="section-heading agent-heading">
      <div><h2>行情智能问答</h2><p>问价格、涨跌和异常；回答只基于已发布报价。</p></div>
      <div class="agent-model-state"><i></i><span>本地模型</span><strong>Qwen2.5 7B</strong></div>
    </div>

    <div class="agent-layout">
      <aside class="agent-thread-panel">
        <button class="agent-new-thread" type="button" :disabled="asking" @click="newConversation">＋ 新建对话</button>
        <div class="agent-thread-title"><span>对话记录</span><small>保存在当前浏览器</small></div>
        <div class="agent-thread-list">
          <button v-for="item in conversations" :key="item.id" :class="['agent-thread', { active: item.id === activeConversationId }]" type="button" :disabled="asking" @click="selectConversation(item.id)">
            <b>{{ item.title }}</b><span>{{ preview(item) }}</span><time>{{ recordTime(item.updatedAt) }}</time>
            <i title="删除对话" @click.stop="removeConversation(item.id)">×</i>
          </button>
        </div>
      </aside>

      <section class="agent-chat-card">
        <header>
          <div><span>{{ activeConversation.title }}</span><strong>直接用自然语言问行情</strong></div>
          <small>每次回答都会查询数据库</small>
        </header>

        <div ref="conversation" class="agent-conversation">
          <article v-for="message in messages" :key="message.id" :class="['agent-message', message.role]">
            <span class="agent-avatar">{{ message.role === 'assistant' ? '问' : '我' }}</span>
            <div>
              <p>{{ message.content }}</p>
              <div v-if="message.sources?.length" class="agent-sources">
                <small>本次回答依据</small>
                <div v-for="source in message.sources" :key="`${source.label}-${source.detail}`">
                  <b>{{ source.label }}</b><span>{{ source.detail }}</span>
                </div>
              </div>
            </div>
          </article>
          <article v-if="asking" class="agent-message assistant pending">
            <span class="agent-avatar">问</span><p><i></i><i></i><i></i> 正在查询已发布报价…</p>
          </article>
        </div>

        <div class="agent-suggestions">
          <span>试着问</span>
          <button v-for="item in suggestedQuestions" :key="item" type="button" :disabled="asking" @click="ask(item)">{{ item }}</button>
        </div>
        <form class="agent-composer" @submit.prevent="ask()">
          <textarea v-model="question" rows="2" :disabled="asking" placeholder="例如：今天 OPPO 哪些型号跌得最多？" @keydown.enter.exact.prevent="ask()"></textarea>
          <button class="primary-action" :disabled="asking || !question.trim()">{{ asking ? '查询中' : '发送问题' }}</button>
        </form>
      </section>

      <aside class="agent-context">
        <section>
          <span>数据状态</span>
          <strong>{{ market.dashboard?.latest_quote_date || '尚未发布' }}</strong>
          <p>最新报价日期</p>
          <dl>
            <div><dt>已发布报价</dt><dd>{{ market.dashboard?.published_quotes || 0 }} 条</dd></div>
            <div><dt>等待复核</dt><dd>{{ market.dashboard?.pending_candidates || 0 }} 条</dd></div>
          </dl>
        </section>
        <section class="agent-boundary">
          <span>回答范围</span>
          <ul>
            <li>查询已发布的报价和涨跌</li>
            <li>定位大幅波动的异常记录</li>
            <li>说明数据不足时，不会猜测价格</li>
          </ul>
        </section>
      </aside>
    </div>
  </section>
</template>
