/**
 * chat.js
 *
 * SSE 事件类型（后端 chat.py 定义）：
 *   status      - 准备中/工具守卫/检索/教学策略等状态更新
 *   routing     - 问题路由结果 { question_type, route }
 *   retrieval   - 知识检索结果 { doc_count, is_rewritten, ... }
 *   explanation - 最终回答 { final_answer, explanation: {...}, tool_calls, ... }
 *   quiz        - 练习题 { quiz_items: [...] }
 *   memory      - 学习记忆更新
 *   done        - 流结束
 *   error       - 发生错误
 */
import { requestChunked } from '../../utils/request';
import { fetchNotebooks } from '../../api/index';

Page({
  data: {
    messages: [
      { role: 'assistant', content: '你好！我是你的学习助手，有什么我可以帮你的吗？', timestamp: Date.now() }
    ],
    inputValue: '',
    isGenerating: false,
    currentStreamText: '',
    currentStatusText: '',    // 流式状态提示（如"正在检索知识库…"）
    notebooks: [],
    selectedNotebookId: 'general',
    selectedNotebookName: '通用',
    showNotebookPicker: false,
    currentSessionId: ''      // 同一页面内保持同一会话
  },

  _streamTask: null,          // 当前 requestTask，用于取消

  onLoad() {
    this._loadNotebooks();
    const storedId = wx.getStorageSync('la_notebook_id');
    if (storedId) this.setData({ selectedNotebookId: storedId });
    // 尝试恢复 session_id
    const sessionId = wx.getStorageSync('la_current_session_id');
    if (sessionId) this.setData({ currentSessionId: sessionId });
  },

  onUnload() {
    if (this._streamTask) {
      try { this._streamTask.abort(); } catch (e) { /* ignore */ }
    }
  },

  async _loadNotebooks() {
    try {
      const list = await fetchNotebooks();
      const storedId = wx.getStorageSync('la_notebook_id');
      const current = list.find(n => n.id === storedId) || list[0];
      this.setData({
        notebooks: list,
        selectedNotebookName: current ? current.name : '通用'
      });
    } catch (e) { /* 静默失败，不影响聊天功能 */ }
  },

  onInput(e) {
    this.setData({ inputValue: e.detail.value });
  },

  toggleNotebookPicker() {
    this.setData({ showNotebookPicker: !this.data.showNotebookPicker });
  },

  selectNotebook(e) {
    const { id, name } = e.currentTarget.dataset;
    this.setData({
      selectedNotebookId: id,
      selectedNotebookName: name,
      showNotebookPicker: false
    });
    wx.setStorageSync('la_notebook_id', id);
  },

  handleSend() {
    const { inputValue, isGenerating } = this.data;
    const question = (inputValue || '').trim();
    if (!question || isGenerating) return;

    const userId = wx.getStorageSync('la_user_id') || '';
    if (!userId) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }

    // 生成或复用 session_id
    let sessionId = this.data.currentSessionId;
    if (!sessionId) {
      sessionId = this._generateUUID();
      this.setData({ currentSessionId: sessionId });
      wx.setStorageSync('la_current_session_id', sessionId);
    }

    // 追加用户消息
    const userMessage = { role: 'user', content: question, timestamp: Date.now() };
    this.setData({
      messages: [...this.data.messages, userMessage],
      inputValue: '',
      isGenerating: true,
      currentStreamText: '',
      currentStatusText: '正在连接学习引擎…'
    });

    // 发起 SSE 流式请求
    const that = this;
    const requestTask = requestChunked('/chat', {
      data: {
        user_id: userId,
        session_id: sessionId,
        question: question,
        subject_id: this.data.selectedNotebookId || 'general'
      }
    });
    this._streamTask = requestTask;

    let decoder = null;
    try {
      if (typeof TextDecoder !== 'undefined') {
        decoder = new TextDecoder('utf-8');
      }
    } catch (e) { /* ignore */ }

    let bufferStr = '';
    let accumulatedAnswer = ''; // 累积最终回答文字

    requestTask.onChunkReceived(function (res) {
      // 解码二进制数据块
      let chunkStr = '';
      try {
        const uint8Array = new Uint8Array(res.data);
        if (decoder) {
          chunkStr = decoder.decode(uint8Array, { stream: true });
        } else {
          // 降级方案
          let str = '';
          for (let i = 0; i < uint8Array.length; i++) {
            str += String.fromCharCode(uint8Array[i]);
          }
          chunkStr = decodeURIComponent(escape(str));
        }
      } catch (e) { return; }

      bufferStr += chunkStr;

      // 按行分割，最后一个可能不完整留在 buffer
      const lines = bufferStr.split('\n');
      bufferStr = lines.pop() || '';

      let currentEvent = '';
      for (const line of lines) {
        if (!line.trim()) { currentEvent = ''; continue; }

        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim();
          continue;
        }

        if (line.startsWith('data:')) {
          const raw = line.slice(5).trim();
          if (raw === '[DONE]') { that._finishStream(accumulatedAnswer); return; }

          let data = {};
          try { data = JSON.parse(raw); } catch (e) { continue; }

          switch (currentEvent) {
            case 'status': {
              // 状态提示（如"正在检索知识库"）
              const msg = data.message || data.detail || '';
              if (msg) that.setData({ currentStatusText: msg });
              break;
            }
            case 'routing': {
              const qt = data.question_type || '';
              const route = data.route || '';
              const label = qt ? `已识别问题类型：${qt}` : '路由分析中…';
              that.setData({ currentStatusText: label });
              break;
            }
            case 'retrieval': {
              const docCount = data.doc_count || 0;
              that.setData({ currentStatusText: `知识检索完成（${docCount} 条）` });
              break;
            }
            case 'explanation': {
              // 这是最核心的回答事件
              // final_answer 是文字回答，explanation 是结构化讲解
              const finalAnswer = data.final_answer || '';
              const explanation = data.explanation || {};
              const explanationText = explanation.thinking || '';

              if (finalAnswer) {
                accumulatedAnswer = finalAnswer;
                that.setData({
                  currentStreamText: accumulatedAnswer,
                  currentStatusText: '正在生成回答…'
                });
              } else if (explanationText && !accumulatedAnswer) {
                accumulatedAnswer = explanationText;
                that.setData({ currentStreamText: accumulatedAnswer });
              }
              break;
            }
            case 'quiz': {
              // 后端发来练习题
              const quizItems = data.quiz_items || [];
              if (quizItems.length > 0) {
                wx.setStorageSync('la_quiz', quizItems);
                that.setData({ currentStatusText: `已生成 ${quizItems.length} 道练习题` });
              }
              break;
            }
            case 'done': {
              that._finishStream(accumulatedAnswer);
              return;
            }
            case 'error': {
              const errMsg = data.error || '处理失败，请重试。';
              that._finishStream('', errMsg);
              return;
            }
            default:
              // 兼容无 event: 行的 data（部分 SSE 实现）
              if (data.final_answer) {
                accumulatedAnswer = data.final_answer;
                that.setData({ currentStreamText: accumulatedAnswer });
              } else if (data.event === 'done' || data.message === '处理完成') {
                that._finishStream(accumulatedAnswer);
                return;
              }
              break;
          }
        }
      }
    });

    // 请求完成（非错误）
    requestTask.then(() => {
      that._finishStream(accumulatedAnswer);
    }).catch(err => {
      console.error('Chat stream error:', err);
      that._finishStream('', '网络连接中断，请重试。');
    });
  },

  _finishStream(finalText, errorText) {
    if (!this.data.isGenerating) return;

    const content = errorText || finalText || '（无内容，请重试）';
    const assistantMsg = {
      role: 'assistant',
      content,
      timestamp: Date.now(),
      isError: !!errorText
    };

    this.setData({
      messages: [...this.data.messages, assistantMsg],
      currentStreamText: '',
      currentStatusText: '',
      isGenerating: false
    });
    this._streamTask = null;
  },

  clearChat() {
    wx.showModal({
      title: '新建对话',
      content: '确定要开始新对话吗？当前对话记录不会丢失。',
      success: (res) => {
        if (res.confirm) {
          // 清除 session_id，下次发送时生成新的
          wx.removeStorageSync('la_current_session_id');
          this.setData({
            messages: [{ role: 'assistant', content: '你好！我是你的学习助手，有什么我可以帮你的吗？', timestamp: Date.now() }],
            currentStreamText: '',
            currentStatusText: '',
            isGenerating: false,
            currentSessionId: ''
          });
        }
      }
    });
  },

  _generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      const r = Math.random() * 16 | 0;
      const v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }
});
