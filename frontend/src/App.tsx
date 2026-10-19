/**
 * App.tsx — Root component
 *
 * Two-tab dashboard:
 *   Tab 1: Fleet Overview — KPI cards, health metric filter buttons,
 *           fleet health trend chart, Top 5 Critical Transformer cards
 *   Tab 2: Asset List — searchable/sortable table of all 987 transformers
 *           → click a row → asset drill-down with 5 metric charts,
 *              work order timeline, inspection photo gallery, AI chat
 *
 * Auth flow (SAML enabled):
 *   - consumeTokenFromUrl() in main.tsx handles the ?token= param after login
 *   - apiFetch() injects Bearer token on all API calls
 *   - 401 response → redirect to /api/saml/login
 */

import { useState, useEffect } from 'react';
import type { TransformerRecord, FleetSummary, MetricFilter } from './types';
import { fetchFleet, fetchSubstations } from './api/client';
import FleetOverview from './components/FleetOverview';
import AssetList from './components/AssetList';
import AssetDrillDown from './components/AssetDrillDown';
import './index.css';

type Tab = 'fleet' | 'assets';

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('fleet');
  const [fleet, setFleet] = useState<FleetSummary | null>(null);
  const [substations, setSubstations] = useState<TransformerRecord[]>([]);
  const [selectedAsset, setSelectedAsset] = useState<TransformerRecord | null>(null);
  const [metricFilter, setMetricFilter] = useState<MetricFilter>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Load both tabs' data in parallel on mount
    Promise.all([fetchFleet(), fetchSubstations()])
      .then(([fleetData, substationData]) => {
        setFleet(fleetData);
        setSubstations(substationData);
        setLoading(false);
      })
      .catch((err: Error) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  const handleAssetSelect = (asset: TransformerRecord) => {
    setSelectedAsset(asset);
    setActiveTab('assets');
  };

  const handleBackToList = () => {
    setSelectedAsset(null);
  };

  if (loading) {
    return (
      <div className="app-loading">
        <div className="spinner" />
        <p>Loading Asset Explorer…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="app-error">
        <h2>Failed to load data</h2>
        <p>{error}</p>
        <button onClick={() => window.location.reload()}>Retry</button>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-brand">
          <span className="header-logo">⚡</span>
          <div>
            <h1>Asset Explorer</h1>
            <p className="header-sub">Substation Health · {fleet?.band_counts.total ?? 0} Transformers · {new Set(substations.map(s => s.substation_id)).size} Substations</p>
          </div>
        </div>
        <nav className="tab-nav">
          <button
            className={`tab-btn ${activeTab === 'fleet' ? 'active' : ''}`}
            onClick={() => { setActiveTab('fleet'); setSelectedAsset(null); }}
          >
            Fleet Overview
          </button>
          <button
            className={`tab-btn ${activeTab === 'assets' ? 'active' : ''}`}
            onClick={() => { setActiveTab('assets'); setSelectedAsset(null); }}
          >
            Asset List
          </button>
        </nav>
      </header>

      <main className="app-main">
        {activeTab === 'fleet' && fleet && (
          <FleetOverview
            fleet={fleet}
            metricFilter={metricFilter}
            onFilterChange={setMetricFilter}
            onAssetSelect={handleAssetSelect}
          />
        )}

        {activeTab === 'assets' && !selectedAsset && (
          <AssetList
            substations={substations}
            onAssetSelect={handleAssetSelect}
          />
        )}

        {activeTab === 'assets' && selectedAsset && (
          <AssetDrillDown
            asset={selectedAsset}
            onBack={handleBackToList}
          />
        )}
      </main>
    </div>
  );
}
