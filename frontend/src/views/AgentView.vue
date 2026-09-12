<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiClient, errorMessage } from '../api'
import { useMarketStore } from '../stores/market'
import type { AgentConversation, AgentConversationMessage, AgentSource } from '../types'

type ChatRole = 'user' | 'assistant'
interface ChatMessage {
  id: string | number
  role: ChatRole
  content: string
  sources?: AgentSource[]
  isGreeting?: boolean
}
const market = useMarketStore()
const question = ref('')
const asking = ref(false)
const conversation = ref<HTMLElement | null>(null)

const emptyConversation: AgentConversation = { id: '', title: '新行情问答', memory: {}, created_at: '', updated_at: '', messages: [] }
const conversations = ref<AgentConversation[]>([])
const activeConversationId = ref('')
const activeConversation = computed(() => conversations.value.find(item => item.id === activeConversationId.value) || conversations.value[0] || emptyConversation)
const greeting: AgentConversationMessage = { id: -1, role: 'assistant', content: '我是你的行情调查与预测助手。我会记住当前对话中的品牌、型号、容量、颜色和日期条件，也能调用历史报价、预测与公开信息搜索工具。', sources: null, tools_used: null, created_at: '' }
const messages = computed(() => activeConversation.value.messages.length ? activeConversation.value.messages : [greeting])
const suggestedQuestions = [
  '今天整体行情怎么样？',
  '今天跌得最多的 5 个型号有哪些？',
  '有哪些涨跌超过 500 元的异常报价？',
  '查一下红米 K80 的最新报价',
  '预测红米 K80 12+256 黑色未来 3 天的回收价',
]

function appendMessage(message: Omit<ChatMessage, 'id'>) {
  activeConversation.value.messages.push({ id: Date.now() + Math.random(), ...message } as AgentConversationMessage)
  activeConversation.value.updated_at = new Date().toISOString()
}

async function newConversation() {
  if (asking.value) return
  const item = await apiClient.createAgentConversation()
  conversations.value.unshift(item)
  activeConversationId.value = item.id
  question.value = ''
  scrollToBottom()
}

function selectConversation(id: string) {
  if (asking.value) return
  activeConversationId.value = id
  scrollToBottom()
}

async function removeConversation(id: string) {
  if (asking.value) return
  try {
    await apiClient.deleteAgentConversation(id)
  } catch (error) {
    return void ElMessage.error(errorMessage(error))
  }
  conversations.value = conversations.value.filter(item => item.id !== id)
  if (!conversations.value.length) await newConversation()
  if (activeConversationId.value === id) activeConversationId.value = conversations.value[0]?.id || ''
}

function preview(item: AgentConversation) {
  const latest = item.messages.at(-1)?.content || '等待提问'
  return latest.replace(/\s+/g, ' ').slice(0, 28)
}

function recordTime(value: string) {
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
  if (!content || asking.value || !activeConversation.value.id) return
  const threadId = activeConversation.value.id
  appendMessage({ role: 'user', content })
  if (activeConversation.value.title === '新行情问答') {
    activeConversation.value.title = content.slice(0, 18)
  }
  question.value = ''
  asking.value = true
  await scrollToBottom()
  try {
    const result = await apiClient.askAgent(content, threadId)
    if (activeConversationId.value === threadId) {
      activeConversation.value.memory = result.memory
      appendMessage({ role: 'assistant', content: result.answer, sources: result.sources })
    }
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

onMounted(async () => {
  try {
    conversations.value = await apiClient.agentConversations()
    if (!conversations.value.length) conversations.value = [await apiClient.createAgentConversation()]
    activeConversationId.value = conversations.value[0].id
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
  await scrollToBottom()
})
</script>

<template>
  <section class="view-panel agent-view">
    <div class="section-heading agent-heading">
      <div><h2>行情智能问答</h2><p>问价格、涨跌、异常和未来走势；内部报价与公开参考会明确区分。</p></div>
      <div class="agent-model-state"><i></i><span>本地模型</span><strong>Qwen2.5 7B</strong></div>
    </div>

    <div class="agent-layout">
      <aside class="agent-thread-panel">
        <button class="agent-new-thread" type="button" :disabled="asking" @click="newConversation">＋ 新建对话</button>
        <div class="agent-thread-title"><span>对话记录</span><small>已持久化</small></div>
        <div class="agent-thread-list">
          <button v-for="item in conversations" :key="item.id" :class="['agent-thread', { active: item.id === activeConversationId }]" type="button" :disabled="asking" @click="selectConversation(item.id)">
            <b>{{ item.title }}</b><span>{{ preview(item) }}</span><time>{{ recordTime(item.updated_at) }}</time>
            <i title="删除对话" @click.stop="removeConversation(item.id)">×</i>
          </button>
        </div>
      </aside>

      <section class="agent-chat-card">
        <header>
          <div><span>{{ activeConversation.title }}</span><strong>直接用自然语言问行情</strong></div>
          <small>自动选择数据库、预测与公开搜索工具</small>
        </header>

        <div ref="conversation" class="agent-conversation">
          <article v-for="message in messages" :key="message.id" :class="['agent-message', message.role]">
            <span class="agent-avatar">{{ message.role === 'assistant' ? '问' : '我' }}</span>
            <div>
              <p>{{ message.content }}</p>
              <div v-if="message.sources?.length" class="agent-sources">
                <small>本次回答依据</small>
                <a v-for="source in message.sources.filter(item => item.url)" :key="`${source.label}-${source.detail}`" :href="source.url || '#'" target="_blank" rel="noopener noreferrer">
                  <b>{{ source.label }}</b><span>{{ source.detail }}</span><em>打开来源 ↗</em>
                </a>
                <div v-for="source in message.sources.filter(item => !item.url)" :key="`${source.label}-${source.detail}`">
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
          <span>当前记忆</span>
          <dl v-if="Object.keys(activeConversation.memory).length" class="agent-memory-list">
            <div v-for="(value, key) in activeConversation.memory" :key="key"><dt>{{ { brand: '品牌', model: '型号', storage: '容量', color: '颜色', last_question: '上次问题' }[key] || key }}</dt><dd>{{ value }}</dd></div>
          </dl>
          <p v-else>提问后将记录当前会话的查询条件</p>
        </section>
        <section class="agent-boundary">
          <span>回答范围</span>
          <ul>
            <li>查询已发布的报价和涨跌</li>
            <li>预测未来 1、3、7、10 天价格区间</li>
            <li>检索公开市场信息并给出依据</li>
            <li>定位大幅波动的异常记录</li>
            <li>说明数据不足时，不会猜测价格</li>
          </ul>
        </section>
      </aside>
    </div>
  </section>
</template>
