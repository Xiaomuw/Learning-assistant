import { fetchLatestQuizBundle, submitPracticeAttempt } from '../../api/index';

Page({
  data: {
    quizList: [],
    currentIndex: 0,
    selectedOption: null,
    showHint: false,
    isSubmitting: false,
    feedback: null,
    submitError: '',
    currentSessionId: '',
    currentNotebookId: 'general',
    isLoading: true
  },

  onLoad() {
    const userId = wx.getStorageSync('la_user_id') || 'anonymous';
    // 先读缓存
    try {
      const cached = wx.getStorageSync('la_quiz') || [];
      if (cached.length > 0) {
        this.setData({ quizList: cached, isLoading: false });
        return;
      }
    } catch (e) { /* ignore */ }

    this._fetchBundle(userId);
  },

  async _fetchBundle(userId) {
    try {
      // 后端返回: { session_id, subject_id, quiz_items: [...] }
      const bundle = await fetchLatestQuizBundle(userId);
      const quizItems = Array.isArray(bundle.quiz_items) ? bundle.quiz_items : [];
      this.setData({
        quizList: quizItems,
        currentSessionId: bundle.session_id || '',
        currentNotebookId: bundle.subject_id || 'general',
        isLoading: false
      });
      if (quizItems.length > 0) {
        wx.setStorageSync('la_quiz', quizItems);
      }
    } catch (err) {
      this.setData({ isLoading: false });
    }
  },

  selectOption(e) {
    if (this.data.feedback) return;
    this.setData({ selectedOption: e.currentTarget.dataset.key, submitError: '' });
  },

  toggleHint() {
    this.setData({ showHint: !this.data.showHint });
  },

  async handleSubmit() {
    const { quizList, currentIndex, selectedOption, currentSessionId, currentNotebookId } = this.data;
    const currentQuiz = quizList[currentIndex];
    if (!currentQuiz || !selectedOption || this.data.feedback || this.data.isSubmitting) return;

    const userId = wx.getStorageSync('la_user_id') || 'anonymous';
    this.setData({ isSubmitting: true, submitError: '' });
    try {
      // 后端返回: { is_correct, correct_option, explanation, option_rationales, memory, mastery_evaluation, personalized_feedback }
      const result = await submitPracticeAttempt({
        user_id: userId,
        session_id: currentSessionId,
        notebookId: currentNotebookId,
        quiz_item: currentQuiz,
        selected_option: selectedOption
      });
      this.setData({ feedback: result });
      // 若返回了 memory，持久化到本地（用于 dashboard 展示）
      if (result.memory) {
        wx.setStorageSync('la_memory', result.memory);
      }
    } catch (err) {
      this.setData({ submitError: err.message || '提交作答失败，请稍后重试。' });
    } finally {
      this.setData({ isSubmitting: false });
    }
  },

  handleNext() {
    const { currentIndex, quizList } = this.data;
    if (currentIndex >= quizList.length - 1) {
      wx.removeStorageSync('la_quiz');
      wx.switchTab({ url: '/pages/chat/chat' });
      return;
    }
    this.setData({
      currentIndex: currentIndex + 1,
      selectedOption: null,
      feedback: null,
      showHint: false,
      submitError: ''
    });
  },

  goToChat() { wx.switchTab({ url: '/pages/chat/chat' }); },

  getOptionStyle(optionKey) {
    const { feedback, selectedOption } = this.data;
    if (!feedback) return selectedOption === optionKey ? 'option-selected' : 'option-default';
    if (optionKey === feedback.correct_option) return 'option-correct';
    if (optionKey === selectedOption && !feedback.is_correct) return 'option-wrong';
    return 'option-dimmed';
  }
});
