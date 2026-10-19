/**
 * MetricChart.tsx — Reusable 90-day trend chart for a single health metric
 *
 * Used in AssetDrillDown for all 5 metric panels.
 * Threshold reference lines show warning/critical boundaries.
 */

import type { MetricPoint } from '../types';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts';

interface Props {
  title: string;
  subtitle: string;
  data: MetricPoint[];
  color: string;
  warningThreshold?: number;
  criticalThreshold?: number;
  yLabel?: string;
}

export default function MetricChart({
  title, subtitle, data, color,
  warningThreshold, criticalThreshold, yLabel
}: Props) {
  const hasData = data.length > 0;

  return (
    <div className="metric-chart-card">
      <div className="chart-header">
        <h4 className="chart-title">{title}</h4>
        <p className="chart-subtitle">{subtitle}</p>
      </div>
      {hasData ? (
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
            <XAxis
              dataKey="timestamp"
              tickFormatter={(d: string) => d.slice(5)}
              tick={{ fontSize: 10, fill: '#718096' }}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#718096' }}
              label={yLabel ? { value: yLabel, angle: -90, position: 'insideLeft', style: { fill: '#718096', fontSize: 10 } } : undefined}
            />
            <Tooltip
              contentStyle={{ background: '#1a202c', border: `1px solid ${color}`, borderRadius: 6 }}
              labelStyle={{ color: '#e2e8f0', fontSize: 11 }}
              formatter={(v: number) => [v.toFixed(3), yLabel ?? 'value']}
            />
            {warningThreshold !== undefined && (
              <ReferenceLine y={warningThreshold} stroke="#f59e0b" strokeDasharray="4 2"
                label={{ value: 'Warning', position: 'right', fill: '#f59e0b', fontSize: 9 }} />
            )}
            {criticalThreshold !== undefined && (
              <ReferenceLine y={criticalThreshold} stroke="#ef4444" strokeDasharray="4 2"
                label={{ value: 'Critical', position: 'right', fill: '#ef4444', fontSize: 9 }} />
            )}
            <Line
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="no-data">No data available for this metric</div>
      )}
    </div>
  );
}
