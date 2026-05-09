export const DEFAULT_NOTEBOOK_ID = "data-structure";

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

export interface Notebook {
  id: string;
  name: string;
  icon: string;
  description: string;
  doc_count: number;
  created_at: string;
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
  key: "A" | "B" | "C" | "D";
  text: string;
}

export interface QuizItem {
  difficulty: "基础" | "变式" | "易错" | string;
  question: string;
  options: QuizOption[];
  correct_option: "A" | "B" | "C" | "D";
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

export interface PracticeAttemptResult {
  is_correct: boolean;
  selected_option?: "A" | "B" | "C" | "D";
  correct_option: "A" | "B" | "C" | "D";
  explanation: string;
  option_rationales: Record<string, string>;
  memory: Memory;
  personalized_feedback?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  isError?: boolean;
  quiz?: QuizItem[];
}

export interface SSEEvent {
  event: string;
  data: any;
}
