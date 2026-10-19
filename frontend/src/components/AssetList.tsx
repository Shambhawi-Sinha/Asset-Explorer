/**
 * AssetList.tsx — Tab 2: Searchable/sortable transformer table
 *
 * Features:
 *   - Client-side search across asset_id, substation_name, region, risk_band
 *   - Column sort (health_score default asc — worst first)
 *   - Risk badge colour-coded (GREEN/AMBER/RED)
 *   - Open emergency WO count highlighted red
 *   - Click row → asset drill-down (AssetDrillDown component)
 */

import { useState, useMemo } from 'react';
import type { TransformerRecord } from '../types';

interface Props {
  substations: TransformerRecord[];
  onAssetSelect: (asset: TransformerRecord) => void;
}

type SortKey = keyof Pick<TransformerRecord,
  'health_score' | 'asset_id' | 'substation_name' | 'risk_band' |
  'thermal_aging_factor' | 'mean_winding_temp' | 'open_emergency_wos'
>;

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'asset_id',            label: 'Asset ID' },
  { key: 'substation_name',     label: 'Substation' },
  { key: 'health_score',        label: 'Health Score' },
  { key: 'risk_band',           label: 'Risk Band' },
  { key: 'thermal_aging_factor',label: 'FAA' },
  { key: 'mean_winding_temp',   label: 'Winding Temp (°C)' },
  { key: 'open_emergency_wos',  label: 'Open Emerg. WOs' },
];

export default function AssetList({ substations, onAssetSelect }: Props) {
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('health_score');
  const [sortAsc, setSortAsc] = useState(true);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return substations.filter(s =>
      !q ||
      s.asset_id.toLowerCase().includes(q) ||
      s.substation_name.toLowerCase().includes(q) ||
      (s.region ?? '').toLowerCase().includes(q) ||
      s.risk_band.toLowerCase().includes(q)
    );
  }, [substations, search]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sortKey] ?? '';
      const bv = b[sortKey] ?? '';
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortAsc ? cmp : -cmp;
    });
  }, [filtered, sortKey, sortAsc]);

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortAsc(prev => !prev);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  return (
    <div className="asset-list">
      <div className="list-controls">
        <input
          className="search-input"
          type="text"
          placeholder="Search asset ID, substation, region, risk band…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <span className="result-count">{sorted.length} / {substations.length} transformers</span>
      </div>

      <div className="table-scroll">
        <table className="asset-table">
          <thead>
            <tr>
              {COLUMNS.map(col => (
                <th
                  key={col.key}
                  className={`sortable ${sortKey === col.key ? 'sorted' : ''}`}
                  onClick={() => handleSort(col.key)}
                >
                  {col.label}
                  {sortKey === col.key && (
                    <span className="sort-arrow">{sortAsc ? ' ▲' : ' ▼'}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(row => (
              <tr
                key={row.asset_id}
                className={`asset-row ${row.open_emergency_wos ? 'has-emergency' : ''}`}
                onClick={() => onAssetSelect(row)}
              >
                <td className="mono">{row.asset_id}</td>
                <td>{row.substation_name}</td>
                <td>
                  <div className="score-bar">
                    <div
                      className={`score-fill fill-${row.risk_band.toLowerCase()}`}
                      style={{ width: `${row.health_score}%` }}
                    />
                    <span className="score-text">{row.health_score.toFixed(1)}</span>
                  </div>
                </td>
                <td>
                  <span className={`risk-badge badge-${row.risk_band.toLowerCase()}`}>
                    {row.risk_band}
                  </span>
                </td>
                <td>{row.thermal_aging_factor?.toFixed(2) ?? '—'}</td>
                <td>{row.mean_winding_temp?.toFixed(1) ?? '—'}</td>
                <td className={row.open_emergency_wos ? 'emergency-count' : ''}>
                  {row.open_emergency_wos ?? 0}
                  {(row.open_emergency_wos ?? 0) > 0 && ' ⚠'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
