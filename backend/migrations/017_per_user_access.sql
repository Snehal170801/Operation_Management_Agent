-- Simple per-user access: instead of picking from shared roles, every non-admin user has their own
-- ticks (Read only / CRUD per module). Each user's ticks live in a private permission set named
-- 'u_' + the first 12 hex digits of their user id (so it fits Users.role and never collides).
-- Existing users keep EXACTLY the access they have today: their current role's permissions are copied.

-- 1. A private set for every non-admin user who does not have one yet.
INSERT INTO dbo.Roles (role_id, name, display_name, description, is_system, defaults_applied)
SELECT NEWID(),
       'u_' + LEFT(REPLACE(LOWER(CAST(u.user_id AS NVARCHAR(36))), '-', ''), 12),
       LEFT('Access for ' + ISNULL(u.email, u.username), 100),
       'Private permission set of one user (managed from the Users screen).',
       0, 1
FROM dbo.Users u
WHERE u.role <> 'admin'
  AND u.role NOT LIKE 'u[_]%'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.Roles r
      WHERE r.name = 'u_' + LEFT(REPLACE(LOWER(CAST(u.user_id AS NVARCHAR(36))), '-', ''), 12)
  );
GO

-- 2. Copy the permissions each user currently gets from their shared role.
INSERT INTO dbo.RolePermissions (role_id, permission)
SELECT pr.role_id, rp.permission
FROM dbo.Users u
JOIN dbo.Roles old ON old.name = u.role
JOIN dbo.RolePermissions rp ON rp.role_id = old.role_id
JOIN dbo.Roles pr ON pr.name = 'u_' + LEFT(REPLACE(LOWER(CAST(u.user_id AS NVARCHAR(36))), '-', ''), 12)
WHERE u.role <> 'admin'
  AND u.role NOT LIKE 'u[_]%'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.RolePermissions x WHERE x.role_id = pr.role_id AND x.permission = rp.permission
  );
GO

-- 3. Point each of those users at their private set.
UPDATE u
SET role = 'u_' + LEFT(REPLACE(LOWER(CAST(u.user_id AS NVARCHAR(36))), '-', ''), 12),
    updated_at = SYSUTCDATETIME()
FROM dbo.Users u
WHERE u.role <> 'admin'
  AND u.role NOT LIKE 'u[_]%';
GO
