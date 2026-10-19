/**
 * WorkOrderTimeline.tsx — Work order history for one transformer
 *
 * Displays chronological work order list most-recent-first.
 * Open emergency WOs highlighted in red (strong risk signal).
 */

import type { WorkOrderRecord } from '../types';

interface Props {
  workorders: WorkOrderRecord[];
}

const WO_TYPE_COLORS = {
  PREVENTIVE:  { bg: '#1a2e1a', border: '#22c55e', text: '#86efac' },
  CORRECTIVE:  { bg: '#2a2a1a', border: '#f59e0b', text: '#fde68a' },
  EMERGENCY:   { bg: '#2a1a1a', border: '#ef4444', text: '#fca5a5' },
};

export default function WorkOrderTimeline({ workorders }: Props) {
  if (!workorders.length) {
    return <p className="no-data">No work orders found for this transformer.</p>;
  }

  return (
    <div className="wo-timeline">
      {workorders.map(wo => {
        const style = WO_TYPE_COLORS[wo.wo_type] ?? WO_TYPE_COLORS.CORRECTIVE;
        const isOpenEmergency = wo.is_open_emergency;
        return (
          <div
            key={wo.wo_id}
            className={`wo-item ${isOpenEmergency ? 'wo-open-emergency' : ''}`}
            style={{ borderLeft: `3px solid ${style.border}`, background: style.bg }}
          >
            <div className="wo-header">
              <span className="wo-date">{wo.created_date}</span>
              <span className="wo-badge" style={{ color: style.text, border: `1px solid ${style.border}` }}>
                {wo.wo_type}
              </span>
              {isOpenEmergency && (
                <span className="wo-open-badge">⚠ OPEN</span>
              )}
              {wo.completion_date && (
                <span className="wo-closed">✓ Closed {wo.completion_date}</span>
              )}
            </div>
            <p className="wo-description">{wo.description}</p>
            {wo.failure_code && (
              <span className="wo-failure-code">Failure code: {wo.failure_code}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
