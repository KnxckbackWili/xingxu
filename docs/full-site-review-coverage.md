# Full-site source review coverage

Baseline: local `f1729c9`; review date: 2026-09-30. This inventory covers all **54 non-test TSX components under frontend/src/pages** plus App route and project-tab wiring.

## What the evidence means

- Source review is code inspection, not a rendered-browser or production-use pass
- A colocated test listed below means a test file exists; it is **not** a claim that its whole suite passed in this review
- Explicit pass counts are in the verification section; the final validator owns full-suite/build results
- All 54 entries have substantive source-inspection evidence, including owner-attested portions; this does not imply every interaction or failure mode was tested
- No real accounts, passwords/tokens, notification deliveries, AI requests, production imports, PostgreSQL backups or restores were exercised

## Per-component inventory

| Component (relative to frontend/src/pages) | Entry/route | Source inspection / outcome | Colocated test file |
|---|---|---|---|
| `FeedbackPage.tsx` | /pm/feedback; /worker/feedback | Source + changed/tested: status filter resets page 1 | `FeedbackPage.test.tsx` |
| `ForbiddenPage.tsx` | App.ProtectedRoute denied state | Source + changed/tested: role-aware return avoids field-role 403 loop | `ForbiddenPage.test.tsx` |
| `LoginPage.tsx` | /login | Source: login return path, role landing, loading/error, auth-store session flow | `LoginPage.test.tsx` |
| `MessagesPage.tsx` | /pm/messages; /worker/messages | Source + owner focused tests: server type filtering, exhausted pagination, stale reads, unread offset reset | `MessagesPage.test.tsx` |
| `NotFoundPage.tsx` | * fallback | Source: 404 fallback and home link | None |
| `StatsPage.tsx` | /pm/stats | Source + changed/tested: all-history vs trend range; effort sample estimate labeling; arithmetic unchanged | `StatsPage.test.tsx` |
| `pm/AiTokensPage.tsx` | /pm/ai-tokens | Source: permission route, create/disable/scopes/one-time token display; no real credentials created or viewed | `AiTokensPage.test.tsx` |
| `pm/AssignPage.tsx` | PeoplePlan nested assignment view | Prior-round source and member-handover errors; availability interaction reviewed by owner | None |
| `pm/DashboardPage.tsx` | /pm/dashboard | Additional source review: four API load, risk filters, actions/navigation; distinct retryable initial error and incident-aware normal filter fixed/tested; diff independently reviewed | `DashboardPage.test.tsx` |
| `pm/GovernancePage.tsx` | /pm/governance; project settings | Parent source review plus independent final diff review: relevant CRUD, permissions, loading/retry and data-preservation paths; aggregate tests recorded by final validator | `GovernancePage.test.tsx` |
| `pm/InboxPage.tsx` | /pm/inbox (intentional direct-only navigation) | Source: direct route intentionally hidden; upload/organize/poll/archive/download handlers; no live AI/provider run | None |
| `pm/InventoryOverviewPage.tsx` | /pm/inventory | Additional source review: filters, pagination, mobile cards, project jump; controlled filter reset and all-visible summary labels fixed/tested; diff independently reviewed | `InventoryOverviewPage.test.tsx` |
| `pm/NotificationChannelsPage.tsx` | /pm/notification-channels | Source: admin route/API, masked configuration, enable/disable/test confirmation; no external test sent | `NotificationChannelsPage.test.tsx` |
| `pm/PeoplePlanPage.tsx` | /pm/people | Source + availability-owner tests: period management entry, create busy guard, list refresh | `PeoplePlanPage.test.tsx` |
| `pm/ProjectListPage.tsx` | /pm/projects | Additional source review: list/progress views, import validation, creation wizard, request identity and submit guard; no new high-impact finding | `ProjectListPage.test.tsx` |
| `pm/StaffingBoard.tsx` | PeoplePlan nested staffing view | Additional source review: week cancellation, filters, conflicts/unavailability, work detail/create, error retry | `StaffingBoard.test.tsx` |
| `pm/SystemBackupPanel.tsx` | /pm/backups (new administrator-only route, System settings menu) | Parent source review plus independent final diff review: relevant CRUD, permissions, loading/retry and data-preservation paths; aggregate tests recorded by final validator | `SystemBackupPanel.test.tsx` |
| `pm/TeamSchedulePage.tsx` | /pm/team-schedule | Source + owner tests: keyboard-native dates, mobile count cells, theme vars, request sequence/error retry | `TeamSchedulePage.test.tsx` |
| `pm/TemplateEditorPage.tsx` | /pm/templates | Parent source review plus independent final diff review: relevant CRUD, permissions, loading/retry and data-preservation paths; aggregate tests recorded by final validator | `TemplateEditorPage.test.tsx` |
| `pm/TemplatePrepsTab.tsx` | template preparation tab | Parent source review plus independent final diff review: relevant CRUD, permissions, loading/retry and data-preservation paths; aggregate tests recorded by final validator | None |
| `pm/TemplateProcurementsTab.tsx` | template procurement tab | Parent source review plus independent final diff review: relevant CRUD, permissions, loading/retry and data-preservation paths; aggregate tests recorded by final validator | None |
| `pm/UsersPage.tsx` | /pm/users | Source + changed/tested: common fresh edit initializer preserves mobile skills, clears unrelated password drafts; empty password omitted, cleared group sent as null | `UsersPage.test.tsx` |
| `pm/VehicleTypesPage.tsx` | /pm/vehicle-types | Parent source review plus independent final diff review: relevant CRUD, permissions, loading/retry and data-preservation paths; aggregate tests recorded by final validator | None |
| `pm/project/ActivityPage.tsx` | project activity/reports wrapper | Source: history/report route/subtab wrapper | None |
| `pm/project/ArchivePage.tsx` | project /archive | Prior-round source/tests: acceptance flow/archive write gates; round3 backend nullable attachment clear reviewed | `ArchivePage.test.tsx` |
| `pm/project/DeliveryPage.tsx` | project /delivery, /files, /archive wrapper | Source wrapper + business backend clone fresh requirements reviewed | `DeliveryPage.test.tsx` |
| `pm/project/EditPage.tsx` | project /edit | Prior-round source/tests: entry-date impact preview and settings permissions | `EditPage.test.tsx` |
| `pm/project/ExportPage.tsx` | project /export | Additional source review: ZIP/Excel/JSON/lifecycle downloads, JSON import, Gantt print, clone; direct import lacks list preflight and clone has loading-only guard | `ExportPage.test.tsx` |
| `pm/project/FilesPage.tsx` | project /files | Additional source review: category/name filter, 10MB upload, downloads/deletion confirmation, load retry; concurrent-upload busy indicator limitation | None |
| `pm/project/GanttView.tsx` | project schedule Gantt subview | Additional source review: task-ID grouping, zoom/lock/date boundaries, parent multi-row shift now waits all results, refreshes and reports partial success (diff reviewed) | `GanttView.test.tsx` |
| `pm/project/HistoryPage.tsx` | project /activity | Source + changed/tested: expand all fetched audit records and collapse | `HistoryPage.test.tsx` |
| `pm/project/InventoryPage.tsx` | project /inventory | Full UI source attested: item/application/movement forms, locks, import/export, history and canManage; replenishment backend fixed; advanced fields remain simplified | `InventoryPage.test.tsx` |
| `pm/project/IssuesPage.tsx` | project /issues | Prior-round source/tests: reopen, archived backend guard, project permissions | `IssuesPage.test.tsx` |
| `pm/project/OverviewPage.tsx` | project /overview | Parent-reported prior-round substantive source review of project planning/execution; no browser verification | `OverviewPage.test.tsx` |
| `pm/project/PreparationPage.tsx` | project /preparation; startup step | Prior-round source/tests: requirement change invalidation, owner fields, review history | `PreparationPage.test.tsx` |
| `pm/project/ProjectLayout.tsx` | /pm/projects/:projectId[/:tab] | Source route mapping + layout owner full source review | `ProjectLayout.test.tsx` |
| `pm/project/ProjectMenu.tsx` | ProjectLayout navigation | Source navigation mapping + layout owner full source review | `ProjectMenu.test.tsx` |
| `pm/project/ReportPage.tsx` | project /reports | Source + existing test: AbortController prevents old period/project display and print; no actual PDF print | `ReportPage.test.tsx` |
| `pm/project/SchedulePage.tsx` | project /schedule; startup step | Parent-reported prior-round substantive source review of project planning/execution; no browser verification | `SchedulePage.test.tsx` |
| `pm/project/SiteHandoverPage.tsx` | project /handover | Additional source review: contacts/primary selection/deletion, entry plan form; hidden EntryPlan fields now preserved and failed contact save retains draft (diff reviewed) | `SiteHandoverPage.test.tsx` |
| `pm/project/SiteInformationPage.tsx` | project vehicles/inventory/handover wrapper | Source wrapper/subtab wiring reviewed | None |
| `pm/project/StartupPage.tsx` | project /start | Parent-reported prior-round substantive source review of project planning/execution; no browser verification | `StartupPage.test.tsx` |
| `pm/project/StartupWork.tsx` | startup work step | Parent-reported prior-round substantive source review of project planning/execution; no browser verification | `StartupWork.test.tsx` |
| `pm/project/TaskPlanPage.tsx` | project /plan | Parent-reported prior-round substantive source review of project planning/execution; no browser verification | `TaskPlanPage.test.tsx` |
| `pm/project/TeamPage.tsx` | project /team; startup step | Prior-round source/tests: unfinished-assignment/member removal and explicit handover errors | `TeamPage.test.tsx` |
| `pm/project/VehicleLifecyclePage.tsx` | project /vehicles | Source + business-owner tests: multi-issue severity, partial-batch recovery, location editing limits | `VehicleLifecyclePage.test.tsx` |
| `worker/MyPage.tsx` | /worker/my | Source: records/personal stats tab wrapper | None |
| `worker/RecordsPage.tsx` | MyPage records; /worker/records redirects to /worker/my | Source: abortable reads, unit-separated totals, month filter/retraction, explicit 200-row cap | `RecordsPage.test.tsx` |
| `worker/TodayPage.tsx` | /worker/today, optional ?entry= | Prior-round source/tests: quantity vs required quality, offline operation identity, safety N/A | `TodayPage.test.tsx` |
| `worker/WorkerIssuesPage.tsx` | /worker/issues | Prior-round source/tests: assigned processing, version conflict refresh, reopen + completed-project next step | `WorkerIssuesPage.test.tsx` |
| `worker/WorkerProjectDetailPage.tsx` | /worker/projects/:projectId | Source portions: parallel read errors, stale project guard, worker-only detail navigation | `WorkerProjectDetailPage.test.tsx` |
| `worker/WorkerProjectsPage.tsx` | /worker/projects | Source: latest response guard, failure vs empty, unknown progress, project navigation | `WorkerProjectsPage.test.tsx` |
| `worker/WorkerSchedulePage.tsx` | /worker/schedule; /pm/my-schedule editable | Source + owner tests: native day buttons, small-screen counts, semantic theme colors | `WorkerSchedulePage.test.tsx` |
| `worker/WorkerStats.tsx` | MyPage stats; /worker/stats redirects to /worker/my | Source portions: independent endpoint errors/retry and personal issue filtering; chart pixels not checked | `WorkerStats.test.tsx` |

## Route and navigation cross-check

App.tsx has role-guarded PM and worker shells; direct routes, legacy redirects, session-recovery failure UI and the catch-all were inspected. ProjectLayout + constants/projectNav.tsx map overview, start, preparation, plan, schedule, vehicles, inventory, handover, issues, team, delivery, files, archive, activity, reports, settings and export. SiteInformation, Delivery, Activity and My wrappers were checked to avoid counting nested components as independent URLs. Inbox is a direct route intentionally absent from the primary menu.

Outside page inventory: layout-owner source review includes PmLayout/WorkerLayout, pmMenu, VisibleTabs, projectNav, index.css/layout.css, a11y patches and ErrorBoundary. Availability review includes new UnavailabilityManager and API wiring (list/edit/cancel, period identity, busy guard and stale-list cancellation reviewed). Auth review includes ProtectedRoute, stores/auth.ts and ChangePasswordModal source; no authentication mutation was performed. Backup navigation now uses the same administrator-only NAV_ACCESS declaration for menu filtering and direct-route protection.

## Verification recorded so far

- Review-owned focused frontend tests: HistoryPage, FeedbackPage, ForbiddenPage, StatsPage: **11 passed** (9 across History/Feedback/Forbidden/Stats, plus 2 UsersPage mobile/desktop tests)
- Layout-owner focused tests: shellAccessibility, MessagesPage, TeamSchedulePage, WorkerSchedulePage: **33 passed**; notification filter backend regression: **1 passed**
- Availability-owner focused tests: **8 frontend + 6 backend passed**; Dashboard/InventoryOverview follow-on: **10 frontend passed**
- Prior second-round independent quality/member/preparation regressions: **11 passed**
- Backups administrator route/menu focused App + pmMenu tests: **28 passed**, including denied direct access and no mutation on page open
- Independent business-record + notification filter regression run: **6 passed**
- Final aggregate: backend 773 passed + 1 static-compression rerun passed; frontend 322 passed across 69 files; production build passed. App test typing-only fix independently reran 8 passing tests

## Explicit limits / business choices

- Browser screenshots, phone-sized pixel layout, dark-mode contrast on actual displays, keyboard end-to-end interactions and print output were not verified in a browser
- Notification/provider/AI integrations and production PostgreSQL backup/restore require a configured runtime; mocks/unit tests cannot prove real delivery or restore
- Effort statistics currently count report rows as 8-hour samples. UI now says this is an estimate, not actual hours or unique person-days; no labor-accounting formula was silently redefined
- Existing automatic 80/90/95 lifecycle thresholds and acceptance-record decision semantics were preserved
- History expansion exposes all records fetched by its endpoint; it does not claim an unlimited backend history export
- Record listing explicitly exposes its existing 200-record limit; it is not a complete high-volume archive

## Final source-review dispositions and remaining limits

Source review is broad rather than a guarantee of defect-free behavior. Addressed and independently re-reviewed: Dashboard initial-error presentation/incident filter; inventory overview controlled filter reset/summary scope; Gantt multi-row partial-write refresh/recovery; SiteHandover hidden-field preservation/failed-save drafts; template-subtab stale mutation refresh; selected-template-only Excel import/export; admin-only reachable backups route; mobile account skills/password draft isolation. PostgreSQL dump environment construction and backup capability metadata were source-reviewed; real PostgreSQL execution was not run. No remaining blocking regression was identified in the reviewed diffs; final aggregate validation remains separate. Lower-priority limits include concurrent file-upload busy state, import preflight parity, and some legacy dialogs using loading state without synchronous duplicate-submit guards.


Final delivery summary: [第三轮全站审查与验证](full-site-review-round3.md). Source-only coverage and the explicit browser/runtime limitations above remain applicable.
