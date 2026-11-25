-- Splits "cases" access into own vs all, and adds the built-in `user` (requester) role.
--   cases:read      -> see your OWN cases (requester)
--   cases:read_all  -> see EVERY case in full detail (staff)
--   cases:create    -> submit a request
-- Existing roles keep exactly what they could do before: anything that could read cases can
-- still read all of them, and anything that could write cases can still create them.

INSERT INTO dbo.RolePermissions (role_id, permission)
SELECT rp.role_id, 'cases:read_all'
FROM dbo.RolePermissions rp
WHERE rp.permission = 'cases:read'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.RolePermissions x WHERE x.role_id = rp.role_id AND x.permission = 'cases:read_all'
  );
GO

INSERT INTO dbo.RolePermissions (role_id, permission)
SELECT rp.role_id, 'cases:create'
FROM dbo.RolePermissions rp
WHERE rp.permission = 'cases:write'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.RolePermissions x WHERE x.role_id = rp.role_id AND x.permission = 'cases:create'
  );
GO

-- Created AFTER the grants above so it does not inherit read_all. Its own permissions are
-- seeded by the app on first start (defaults_applied = 0).
INSERT INTO dbo.Roles (name, display_name, description, is_system)
SELECT 'user', 'User', 'Submits purchase requests and follows the agents working on their own requests.', 1
WHERE NOT EXISTS (SELECT 1 FROM dbo.Roles WHERE name = 'user');
GO

-- Case ownership lookups and the per-user daily request limit.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Cases_requester_created')
    CREATE INDEX IX_Cases_requester_created ON dbo.Cases(requester_id, created_at DESC);
GO
