/**
 * TIA Domain Types
 * Central type definitions for Traffic Impact Assessment data structures.
 * These types mirror the JSON schema used between the frontend and backend.
 */

export interface TiaProject {
  name?: string;
  location?: string;
  cc_number?: string;
  prepared_by?: string;
  report_date?: string;
  selected_site_details?: Record<string, unknown>;
}

export interface TiaInputs {
  aadt?: number;
  growth_rate_percent?: number;
  heavy_vehicle_percent?: number;
  right_turn_percent?: number;
  peak_hour_factor?: number;
  directional_split_percent?: number;
  [key: string]: unknown;
}

export interface TiaResults {
  queue_length_m?: number;
  vcr?: number;
  delay_seconds?: number;
  level_of_service?: string;
  [key: string]: unknown;
}

export interface TiaPayload {
  project?: TiaProject;
  inputs?: TiaInputs;
  results?: TiaResults;
  notes?: TiaNote[];
  report_variant?: 'short' | 'detailed' | string;
  executive_summary?: string;
  [key: string]: unknown;
}

export interface TiaNote {
  id?: string;
  text?: string;
  category?: string;
  severity?: 'info' | 'warning' | 'critical';
}

export interface DraftCreateRequest {
  title: string;
  payload: TiaPayload;
}

export interface DraftCreateResponse {
  editor_url: string;
}

export interface HealthCheckResponse {
  status: string;
  version?: string;
  uptime_seconds?: number;
  draft_store?: { type: string; count?: number; [k: string]: unknown };
  rate_limiter?: { type: string; [k: string]: unknown };
}

export interface VerifyFormulasRequest {
  failures: FormulaFailure[];
}

export interface FormulaFailure {
  id: string;
  name: string;
  group: string;
  reference: number;
  actual: number;
  deviation: number;
  error: string;
}

export interface VerifyFormulasResponse {
  status: string;
  failure_count?: number;
  analysis?: string;
  [key: string]: unknown;
}

export interface AddressCandidate {
  lat: number;
  lon: number;
  displayName: string;
  road?: string | null;
  houseNumber?: string;
  provider?: string;
}

export interface RateLimitMeta {
  limit: number;
  remaining: number;
  reset_epoch: number;
}

export type ReportMode = 'short' | 'detailed';
