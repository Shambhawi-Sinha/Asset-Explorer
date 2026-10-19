// ─── Domain types matching FastAPI response models ───────────────────────────

export type RiskBand = 'GREEN' | 'AMBER' | 'RED';

export interface TransformerRecord {
  asset_id: string;
  substation_id: string;
  substation_name: string;
  region?: string;
  voltage_kv?: number;
  rating_mva?: number;
  health_score: number;
  risk_band: RiskBand;
  mean_winding_temp?: number;
  hotspot_temp?: number;
  thermal_aging_factor?: number;
  overload_severity?: number;
  tap_changer_stress?: number;
  load_temp_sensitivity?: number;
  last_inspection_date?: string;
  photo_record_id?: string;
  open_emergency_wos?: number;
  total_work_orders?: number;
}

export interface BandCounts {
  green: number;
  amber: number;
  red: number;
  total: number;
}

export interface TopTransformer {
  asset_id: string;
  substation_name: string;
  health_score: number;
  risk_band: RiskBand;
  open_emergency_wos: number;
}

export interface TrendPoint {
  date: string;
  avg_health_score: number;
  red_count: number;
}

export interface FleetSummary {
  band_counts: BandCounts;
  top_critical: TopTransformer[];
  health_trend: TrendPoint[];
}

export interface MetricPoint {
  timestamp: string;
  value: number;
}

export interface WorkOrderRecord {
  wo_id: string;
  created_date: string;
  wo_type: 'PREVENTIVE' | 'CORRECTIVE' | 'EMERGENCY';
  description: string;
  failure_code?: string;
  completion_date?: string;
  is_open_emergency: boolean;
}

export interface AssetMetrics {
  thermal: MetricPoint[];
  overload: MetricPoint[];
  tap: MetricPoint[];
  winding: MetricPoint[];
  workorders: WorkOrderRecord[];
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  sources?: string[];
}

// ─── Auth types ───────────────────────────────────────────────────────────────

export interface JwtClaims {
  sub: string;            // user email
  name: string;
  iat: number;
  exp: number;
  access_transformer: boolean;
  access_generation: boolean;
}

// ─── Filter types (Fleet Overview tab) ────────────────────────────────────────

export type MetricFilter = 'all' | 'thermal' | 'overload' | 'tap' | 'winding';
