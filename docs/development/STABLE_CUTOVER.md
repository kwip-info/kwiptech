# Stable cutover plan

1. Inventory and recovery: record current deployment and capture a database backup;
   inspect repository history before making source public.
2. Retirement: remove hosted handlers, authentication, billing jobs, and dependencies;
   return 410 without processing payloads; preserve historical schema.
3. Existing-app validation: run the production URL config under tests, migrate a
   pre-cutover database in isolation, retain Digest intake, and verify bundled docs.
4. Release: publish tested PyScoped 2.0.0, rename repository to kwiptech, make source
   public, push reviewed commits, and verify CI/deployment and external behavior.
5. Reconcile: record receipts and rollback instructions in enterprise operations.

Phase 2 tests: 102 passing, including 50 retired-route/method combinations with
zero database queries and no CSRF requirement, body-read rejection, public pages
without database access, retained Digest intake, and documentation traversal checks.
Migration state check passes; old migration dependencies remain available.
Final deployment/release evidence is pending phase 4.

Phase 3 complete: 102 tests also pass against PostgreSQL 18 using production settings.
A restored pre-cutover production backup migrates with only pyscoped.0001_initial.
Historical row counts remain unchanged. An isolated mapping of an existing lead
table passed baseline, audited write, chain verification, and cross-scope denial;
trial writes were rolled back. No production lead was changed.
Desktop preview verified homepage and free-library pricing with Digest terms intact.
