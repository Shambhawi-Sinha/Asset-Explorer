/**
 * FleetOverview.tsx — Tab 1: Fleet Overview
 *
 * Panels:
 *   1. KPI cards — fleet totals (GREEN / AMBER / RED counts + total)
 *   2. Metric filter buttons — dynamically highlight top transformers
 *      by selected health metric (all | thermal | overload | tap | winding)
 *   3. Fleet health trend chart — avg health score + RED count over 30 days
 *   4. Top 5 Critical Transformer cards — worst health score assets
 */

import type { FleetSummary, TopTransformer, MetricFilter } from '../types';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine
} from 'recharts';

interface Props {
  fleet: FleetSummary;
  metricFilter: MetricFilter;
  onFilterChange: (f: MetricFilter) => void;
  onAssetSelect: (asset: { asset_id: string; substation_name: string; health_score: number; risk_band: 'GREEN' | 'AMBER' | 'RED'; open_emergency_wos: number }) => void;
}

const FILTERS: { key: MetricFilter; label: string; description: string }[] = [
  { key: 'all',      label: 'All Metrics',     description: 'Composite health score' },
  { key: 'thermal',  label: 'Thermal Aging',   description: 'FAA (IEC 60076-7)' },
  { key: 'overload', label: 'Overload',        description: 'MVA actual / rated' },
  { key: 'tap',      label: 'Tap Changer',     description: 'Daily TPOSC ops' },
  { key: 'winding',  label: 'Winding Temp',    description: 'Rolling 24h avg °C' },
];

const BAND_COLORS = { GREEN: '#22c55e', AMBER: '#f59e0b', RED: '#ef4444' };

export default function FleetOverview({ fleet, metricFilter, onFilterChange, onAssetSelect }: Props) {
  const { band_counts, top_critical, health_trend } = fleet;

  return (
    <div className="fleet-overview">
      {/* KPI Cards */}
      <section className="kpi-section">
        <KpiCard label="Total Transformers" value={band_counts.total} className="kpi-total" />
        <KpiCard label="🟢 Green" value={band_counts.green} className="kpi-green" />
        <KpiCard label="🟡 Amber" value={band_counts.amber} className="kpi-amber" />
        <KpiCard label="🔴 Red — Critical" value={band_counts.red} className="kpi-red" highlight={band_counts.red > 0} />
      </section>

      {/* Metric Filter Buttons */}
      <section className="filter-section">
        <h3 className="section-label">View by Metric</h3>
        <div className="filter-buttons">
          {FILTERS.map(f => (
            <button
              key={f.key}
              className={`filter-btn ${metricFilter === f.key ? 'active' : ''}`}
              onClick={() => onFilterChange(f.key)}
              title={f.description}
            >
              {f.label}
            </button>
          ))}
        </div>
      </section>

      {/* Fleet Health Trend Chart */}
      <section className="trend-section">
        <h3 className="section-label">Fleet Health Trend — Last 30 Days</h3>
        <div className="chart-container">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={health_trend} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis
                dataKey="date"
                tickFormatter={(d: string) => d.slice(5)}   // show MM-DD
                tick={{ fontSize: 11, fill: '#a0aec0' }}
              />
              <YAxis yAxisId="score" domain={[0, 100]} tick={{ fontSize: 11, fill: '#a0aec0' }} />
              <YAxis yAxisId="red" orientation="right" tick={{ fontSize: 11, fill: '#ef4444' }} />
              <Tooltip
                contentStyle={{ background: '#1a202c', border: '1px solid #4a5568', borderRadius: 6 }}
                labelStyle={{ color: '#e2e8f0' }}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: '#a0aec0' }} />
              <ReferenceLine yAxisId="score" y={70} stroke="#22c55e" strokeDasharray="4 2" label={{ value: 'GREEN', position: 'right', fill: '#22c55e', fontSize: 10 }} />
              <ReferenceLine yAxisId="score" y={40} stroke="#f59e0b" strokeDasharray="4 2" label={{ value: 'AMBER', position: 'right', fill: '#f59e0b', fontSize: 10 }} />
              <Line
                yAxisId="score"
                type="monotone"
                dataKey="avg_health_score"
                stroke="#60a5fa"
                strokeWidth={2}
                dot={false}
                name="Avg Health Score"
              />
              <Line
                yAxisId="red"
                type="monotone"
                dataKey="red_count"
                stroke="#ef4444"
                strokeWidth={1.5}
                dot={false}
                name="RED Count"
                strokeDasharray="4 2"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* Top Critical Transformer Cards */}
      <section className="top-critical-section">
        <h3 className="section-label">
          Top Critical Transformers
          {metricFilter !== 'all' && <span className="filter-badge"> · {FILTERS.find(f => f.key === metricFilter)?.label}</span>}
        </h3>
        <div className="top-critical-grid">
          {top_critical.map((t, i) => (
            <TopTransformerCard
              key={t.asset_id}
              transformer={t}
              rank={i + 1}
              onClick={() => onAssetSelect(t)}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function KpiCard({ label, value, className, highlight }: {
  label: string; value: number; className?: string; highlight?: boolean;
}) {
  return (
    <div className={`kpi-card ${className ?? ''} ${highlight ? 'kpi-highlight' : ''}`}>
      <span className="kpi-value">{value}</span>
      <span className="kpi-label">{label}</span>
    </div>
  );
}

function TopTransformerCard({ transformer, rank, onClick }: {
  transformer: TopTransformer; rank: number; onClick: () => void;
}) {
  const { asset_id, substation_name, health_score, risk_band, open_emergency_wos } = transformer;
  return (
    <button className={`top-transformer-card band-${risk_band.toLowerCase()}`} onClick={onClick}>
      <div className="card-rank">#{rank}</div>
      <div className="card-info">
        <div className="card-name">{substation_name}</div>
        <div className="card-id">{asset_id}</div>
      </div>
      <div className="card-score">
        <span className="score-value">{health_score.toFixed(0)}</span>
        <span className={`risk-badge badge-${risk_band.toLowerCase()}`}>{risk_band}</span>
      </div>
      {open_emergency_wos > 0 && (
        <div className="card-alert">⚠ {open_emergency_wos} open emergency WO{open_emergency_wos > 1 ? 's' : ''}</div>
      )}
    </button>
  );
}
