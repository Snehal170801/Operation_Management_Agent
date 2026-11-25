-- Production RBAC: roles and their permissions live in the database (editable by admins),
-- plus an audit log of security-relevant actions.

IF OBJECT_ID('dbo.Roles', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Roles (
        role_id           UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        name              NVARCHAR(30)     NOT NULL,        -- immutable slug; this is what Users.role stores (same size as Users.role)
        display_name      NVARCHAR(100)    NOT NULL,
        description       NVARCHAR(300)    NULL,
        is_system         BIT              NOT NULL DEFAULT 0, -- built-in: cannot be deleted
        defaults_applied  BIT              NOT NULL DEFAULT 0, -- default permissions seeded once, never re-applied
        created_at        DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at        DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_Roles_name')
    CREATE UNIQUE INDEX UX_Roles_name ON dbo.Roles(name);
GO

IF OBJECT_ID('dbo.RolePermissions', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.RolePermissions (
        role_id     UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Roles(role_id) ON DELETE CASCADE,
        permission  NVARCHAR(100)    NOT NULL,   -- "resource:action", validated against the code catalog
        PRIMARY KEY (role_id, permission)
    );
END
GO

-- Built-in roles (their permissions are seeded by the app on first start).
INSERT INTO dbo.Roles (name, display_name, description, is_system)
SELECT v.name, v.display_name, v.description, 1
FROM (VALUES
    ('admin',   'Administrator', 'Full access, including users, roles, audit log and system health.'),
    ('manager', 'Manager',       'Create and change cases, stock, vendors and approvals.'),
    ('viewer',  'Viewer',        'Read-only access to operations data.')
) AS v(name, display_name, description)
WHERE NOT EXISTS (SELECT 1 FROM dbo.Roles r WHERE r.name = v.name);
GO

-- Users.role now references a real role (was a hard-coded CHECK of three names).
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_Users_role')
    ALTER TABLE dbo.Users DROP CONSTRAINT CK_Users_role;
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_Users_role')
    ALTER TABLE dbo.Users ADD CONSTRAINT FK_Users_role FOREIGN KEY (role) REFERENCES dbo.Roles(name);
GO

IF OBJECT_ID('dbo.AuditLog', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.AuditLog (
        audit_id        BIGINT IDENTITY(1,1) PRIMARY KEY,
        actor_user_id   UNIQUEIDENTIFIER NULL,
        actor_username  NVARCHAR(254)    NULL,
        action          NVARCHAR(100)    NOT NULL,   -- e.g. auth.login, user.update, role.delete, authz.denied
        outcome         NVARCHAR(20)     NOT NULL DEFAULT 'success', -- success | failure | denied
        target_type     NVARCHAR(50)     NULL,
        target_id       NVARCHAR(100)    NULL,
        detail          NVARCHAR(MAX)    NULL,       -- JSON
        ip_address      NVARCHAR(64)     NULL,
        created_at      DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_AuditLog_created_at')
    CREATE INDEX IX_AuditLog_created_at ON dbo.AuditLog(created_at DESC);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_AuditLog_action')
    CREATE INDEX IX_AuditLog_action ON dbo.AuditLog(action, created_at DESC);
GO
