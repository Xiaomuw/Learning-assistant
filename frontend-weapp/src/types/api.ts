export const DEFAULT_NOTEBOOK_ID = "data-structure";

export type OptionKey = "A" | "B" | "C" | "D";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

export interface AuthTokenEnvelope {
  user: AuthUser;
  access_token: string;
  refresh_token: string;
}

export interface UserProfile {
  user_id: string;
  display_name: string;
  agent_style_name: string;
  agent_style_prompt: string;
  onboarding_completed: boolean;
}

export interface Notebook {
  id: string;
  name: string;
  icon: string;
  description: string;
  doc_count: number;
  created_at: string;
}

export interface NotebookKnowledgeStatus {
  notebookId: string;
  collection_name: string;
  doc_count: number;
  shared_doc_count: number;
  personal_doc_count: number;
  chapter_count: number;
  exam_pattern_count: number;
  question_count: number;
  url_count: number;
  pdf_count: number;
  personal_pdf_count: number;
  personal_url_count: number;
  personal_ready: boolean;
  embedding_ready: boolean;
  coverage_score: number;
  coverage_level: "empty" | "sparse" | "partial" | "ready" | string;
  missing_doc_types: string[];
  suggested_actions: string[];
  retrieval_ready: boolean;
}

export interface Memory {
  weak_points: string[];
  error_count: Record<string, number>;
  recent_topics: string[];
  last_session?: string;
}

export interface KnowledgeMastery {
  user_id: string;
  subject_id: string;
  knowledge_point: string;
  chapter_id?: string;
  topic_id?: string;
  concept_id?: string;
  concept_name?: string;
  concept_mapping_status?: string;
  exposure_count: number;
  attempt_count: number;
  correct_count: number;
  wrong_count: number;
  mastery_score: number;
  mastery_level: "mastered" | "learning" | "weak" | string;
  last_seen_at: string;
  last_practiced_at: string;
  updated_at: string;
}

export interface KnowledgeMasteryPayload {
  user_id: string;
  subject_id?: string | null;
  items: KnowledgeMastery[];
}

export interface QuizOption {
  key: OptionKey;
  text: string;
}

export interface QuizItem {
  difficulty: "基础" | "变式" | "易错" | string;
  question: string;
  options: QuizOption[];
  correct_option: OptionKey;
  explanation: string;
  option_rationales: Record<string, string>;
  knowledge_point: string;
  source_type: string;
  source_name: string;
  source_year?: number | null;
  question_id: string;
  hint?: string;
  subject_id?: string;
  notebook_id?: string;
  chapter_id?: string;
  topic_id?: string;
  concept_id?: string;
  concept_name?: string;
  source_session_id?: string;
}

export interface LatestQuizPayload {
  session_id: string;
  subject_id: string;
  quiz_items: QuizItem[];
}

export interface PracticeRecommendationPayload {
  subject_id: string;
  items: QuizItem[];
}

export interface Explanation {
  topic?: string;
  thinking?: string;
  steps?: string[];
  mistakes?: string;
  similar?: string[];
}

export interface MasteryScoreBreakdown {
  accuracy: number;
  completeness: number;
  understanding_depth: number;
  confidence: number;
  rag_doc_count: number;
  low_confidence: boolean;
  issues: string[];
}

export interface MasteryEvaluationResult {
  subject_id: string;
  knowledge_point: string;
  chapter_id?: string;
  topic_id?: string;
  concept_id?: string;
  concept_name?: string;
  concept_mapping_status?: string;
  answer_type: "mcq" | "blank" | "short_answer" | string;
  normalized_answer: string;
  is_correct: boolean;
  score: number;
  mastery_score: number;
  mastery_level: "mastered" | "learning" | "weak" | string;
  weak_points: string[];
  feedback: string;
  score_breakdown: MasteryScoreBreakdown;
  retrieval_diagnosis: string;
  reference_doc_count: number;
}

export interface PracticeAttemptResult {
  is_correct: boolean;
  selected_option?: OptionKey;
  correct_option: OptionKey;
  explanation: string;
  option_rationales: Record<string, string>;
  memory: Memory;
  session_memory?: Record<string, any> | null;
  mastery_evaluation?: MasteryEvaluationResult | null;
  personalized_feedback?: string;
  analysis_status?: "queued" | "completed" | "duplicate" | string;
}

export interface QuizRecommendedOption {
  label: string;
  value: string;
  source: "recent_topic" | "weak_point" | "default" | "current_context" | string;
}

export interface QuizRequestResolution {
  is_quiz_request: boolean;
  action:
    | "generate_practice_pack"
    | "clarify_quiz_request"
    | "continue_practice"
    | "normal_qa"
    | string;
  intent:
    | "quiz_generation"
    | "continue_quiz_generation"
    | "quiz_answer_check"
    | "normal_qa"
    | string;
  topic: string | null;
  subject_id?: string | null;
  requested_topic?: string | null;
  previous_topic?: string | null;
  active_topic?: string | null;
  should_switch_topic?: boolean;
  topic_resolution_reason?: string;
  source:
    | "explicit_user_input"
    | "current_question"
    | "last_topic"
    | "recent_topic"
    | "weak_point"
    | "unknown"
    | string;
  question_type:
    | "single_choice"
    | "multiple_choice"
    | "true_false"
    | "short_answer"
    | "mixed"
    | "unknown"
    | string;
  difficulty: "easy" | "medium" | "hard" | "adaptive" | "unknown" | string;
  count: number | null;
  target_module: "practice" | "qa" | string;
  need_clarification: boolean;
  clarification_reason?: string | null;
  recommended_options: QuizRecommendedOption[];
  custom_input_placeholder?: string | null;
  reason: string;
}

export interface QuizClarificationPanel {
  title: string;
  description: string;
  recommended_options: QuizRecommendedOption[];
  question_type_options: QuizRecommendedOption[];
  difficulty_options: QuizRecommendedOption[];
  count_options: QuizRecommendedOption[];
  custom_input_placeholder: string;
}

export type LearningCenterStatus = "unstarted" | "weak" | "learning" | "mastered";

export interface LearningCenterStatusCounts {
  unstarted?: number;
  weak?: number;
  learning?: number;
  mastered?: number;
  [key: string]: number | undefined;
}

export interface LearningCenterConcept {
  concept_id: string;
  concept_name: string;
  subject_id: string;
  chapter_id?: string;
  topic_id?: string;
  aliases: string[];
  importance: "high" | "medium" | "low" | string;
  exam_frequency: "high" | "medium" | "low" | string;
  prerequisites: string[];
  p_mastery: number;
  mastery_score?: number;
  coverage_ratio?: number;
  status: LearningCenterStatus | string;
  status_counts?: LearningCenterStatusCounts;
  weak_count?: number;
  tested: boolean;
  test_status: "untested" | "tested" | string;
  attempt_count: number;
  correct_count: number;
  wrong_count: number;
  question_count: number;
  last_practiced_at?: string | null;
  updated_at?: string | null;
}

export interface LearningCenterTopic {
  topic_id: string;
  topic_name: string;
  subject_id: string;
  chapter_id: string;
  mastery_score: number;
  coverage_ratio: number;
  status_counts: LearningCenterStatusCounts;
  weak_count: number;
  tested_count: number;
  untested_count: number;
  tested_ratio: number;
  attempt_count: number;
  correct_count: number;
  wrong_count: number;
  updated_at?: string | null;
  concepts: LearningCenterConcept[];
}

export interface LearningCenterChapter {
  chapter_id: string;
  chapter_name: string;
  subject_id: string;
  mastery_score: number;
  coverage_ratio: number;
  status_counts: LearningCenterStatusCounts;
  weak_count: number;
  tested_count: number;
  untested_count: number;
  tested_ratio: number;
  attempt_count: number;
  correct_count: number;
  wrong_count: number;
  updated_at?: string | null;
  topics: LearningCenterTopic[];
}

export interface LearningCenterSubject {
  subject_id: string;
  subject_name: string;
  mastery_score: number;
  coverage_ratio: number;
  status_counts: LearningCenterStatusCounts;
  weak_count: number;
  tested_count: number;
  untested_count: number;
  tested_ratio: number;
  attempt_count: number;
  correct_count: number;
  wrong_count: number;
  updated_at?: string | null;
  chapters: LearningCenterChapter[];
}

export interface LearningCenterNextMove {
  concept_id: string;
  concept_name: string;
  subject_id: string;
  chapter_id?: string;
  topic_id?: string;
  action?: "review_weak" | "practice_learning" | "start_high_value" | "none" | string;
  reason: string;
  subject_name?: string | null;
  chapter_name?: string | null;
  topic_name?: string | null;
  status?: LearningCenterStatus | string | null;
  p_mastery?: number | null;
  recommended_action?: "qa" | "practice" | "review" | null;
}

export interface LearningCenterResponse {
  user_id: string;
  subject_id?: string | null;
  subjects: LearningCenterSubject[];
  next_move?: LearningCenterNextMove | null;
  generated_at?: string | null;
}

export interface PracticePackPayload {
  user_id: string;
  session_id?: string;
  subject_id?: string;
  request_text: string;
  current_practice_question?: QuizItem | null;
  last_practice_pack?: QuizItem[];
  context?: Record<string, any>;
}

export interface PracticePackResponse {
  subject_id: string;
  quiz_request: QuizRequestResolution;
  quiz_clarification?: QuizClarificationPanel | null;
  items: QuizItem[];
  generation_status?: Record<string, any>;
  errors?: Array<Record<string, any>>;
  message?: string;
}

export interface LearningCenterPracticeTarget {
  subjectId: string;
  subjectName?: string;
  chapterId?: string;
  chapterName?: string;
  topicId?: string;
  topicName?: string;
  conceptId: string;
  conceptName: string;
  reason?: string;
}

export interface ChatProcessStage {
  key: string;
  label: string;
  detail: string;
  status: "running" | "completed" | "failed";
  elapsed?: number;
}

export interface ChatProcessModelAttempt {
  model_id?: string;
  modelId?: string;
  role?: string;
  status?: string;
  reason?: string;
}

export interface ChatProcessExecution {
  mode?: string;
  degraded?: boolean;
  modelId?: string;
  modelFamily?: string;
  modelProvider?: string;
  primaryModelId?: string;
  fallbackModelId?: string;
  fallbackUsed?: boolean;
  fallbackReason?: string;
  streamingMode?: string;
  streamingTokenCount?: number;
  streamingDegradedReason?: string;
  modelLatencyMs?: number;
  modelAttempts?: ChatProcessModelAttempt[];
  callStatus?: "ok" | "failed" | "fallback" | "unknown" | string;
}

export interface ChatStreamDiagnostics {
  transport?: "chunked" | "sync_fallback" | string;
  chunkSupported?: boolean;
  chunkCount?: number;
  parsedEventCount?: number;
  realTokenDeltaCount?: number;
  syntheticDeltaCount?: number;
  firstChunkMs?: number;
  firstRealTokenDeltaMs?: number;
  elapsedMs?: number;
  degradedReason?: string;
  detail?: string;
}

export interface ChatProcessToolCall {
  name: string;
  label: string;
  success: boolean;
  argsSummary: string;
  error?: string;
  docCount?: number;
}

export interface ChatProcess {
  currentStage?: string;
  stages: ChatProcessStage[];
  reasoningSummary?: string;
  reasoningTrace?: string;
  execution?: ChatProcessExecution;
  streamDiagnostics?: ChatStreamDiagnostics;
  toolCalls?: ChatProcessToolCall[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  isError?: boolean;
  quiz?: QuizItem[];
  quizRequest?: QuizRequestResolution;
  quizClarification?: QuizClarificationPanel;
  explanation?: Explanation;
  process?: ChatProcess;
  questionType?: string;
  route?: string;
}

export interface SSEEvent {
  event: string;
  data: any;
}

export interface ChatSessionWire {
  id: string;
  subject_id: string;
  title: string;
  messages: ChatMessage[];
  updated_at: string;
}

export interface ChatSession {
  id: string;
  title: string;
  notebookId: string;
  updatedAt: number;
  messageCount: number;
}

export interface ModelHealth {
  chat_model: string;
  chat_model_ok: boolean;
  chat_model_error?: string;
}
