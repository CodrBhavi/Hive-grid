# HiveGrid frontend demo

HiveGrid is a responsive React, TypeScript and Vite frontend demonstration for CodeKshetra SUS-02: A Society of Energy Agents. It includes eight pages, 56 varied sample household profiles, interactive controls and charts, and a replaceable local mock service layer.

## Run locally

Requirements: Node.js 18 or newer.

```bash
npm install
npm run dev
```

Open the local URL printed by Vite. To create a production build, run `npm run build`; to preview it, run `npm run preview`.

## What is included

- Overview and Society Command Center with demo metrics and Recharts visualizations.
- Home Agents with search, status and solar filters, sorting, and a household detail panel.
- Energy Network visualization with interactive home and agent nodes.
- Simulation Studio with scenario controls, sliders, speed, timeline, and sample comparisons.
- Resident Controls with editable preferences, example instructions, confirmations, and demo overrides.
- Activity Log filters and minimal Settings.
- Central mock data in `src/data` and the service contract and local implementation in `src/services/simulationService.ts`.

All values, events, trades, and savings comparisons are sample data. No simulator, backend, database, smart meters, or grid are connected. Replace the implementation behind `SimulationService` when integrating the future API.

## Portal demonstration

The welcome screen offers separate Society Admin and Resident demo access. The mock role session is stored in browser local storage; it is not real authentication or a security boundary. Resident accounts require a household invitation code created in the Admin Home Management screen. Admins can maintain local household profiles, issue demo invitations, review resident requests, update request statuses, and view sample analytics. Residents can see only their assigned sample household, submit and track requests, cancel eligible requests, and read society updates. Request and invitation state is stored locally in the browser for this prototype.
