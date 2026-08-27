export type JsonObject = Record<string, unknown>;

export interface Task {
  id: string;
  task_type: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  effective_status?: string;
  attempts: number;
  error?: string | null;
  failure_category?: string | null;
  failure_code?: string | null;
  created_at: string;
  updated_at: string;
  result?: JsonObject | null;
}

export interface Book {
  book_id: string;
  book_name: string;
  author_name?: string;
  cover?: string;
  is_paid?: number | null;
  total_word_count?: number;
  last_seen_at?: string;
  downloaded?: boolean;
  position?: number;
}

export interface Download {
  id: string;
  book_id: string;
  book_name: string;
  output_path: string;
  file_size: number;
  sha256: string;
  created_at: string;
}

export interface EventItem {
  id: string;
  event_type: string;
  component: string;
  category?: string;
  code?: string;
  message: string;
  created_at: string;
  slot_id?: string;
}

export interface IdentitySlot {
  slot_id: string;
  profile_id?: string;
  app_version?: string;
  transport_profile?: string;
  origin?: string;
  has_identity: boolean;
  identity_status?: string | null;
  last_validated_at?: string | null;
  updated_at?: string;
}

export interface ArchiveItem {
  id: string;
  archive_type: string;
  period: string;
  status: string;
  record_count: number;
  file_size: number;
  sha256: string;
  updated_at: string;
  error?: string | null;
}
