-- RBAC: roles become admin | manager | viewer (was admin | user).

UPDATE dbo.Users SET role = 'viewer' WHERE role = 'user';
GO

-- Replace the old DEFAULT 'user' with a least-privilege default.
DECLARE @df NVARCHAR(200) = (
    SELECT dc.name
    FROM sys.default_constraints dc
    JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
    WHERE dc.parent_object_id = OBJECT_ID('dbo.Users') AND c.name = 'role'
);
IF @df IS NOT NULL EXEC('ALTER TABLE dbo.Users DROP CONSTRAINT [' + @df + ']');
GO

IF NOT EXISTS (SELECT 1 FROM sys.default_constraints WHERE name = 'DF_Users_role')
    ALTER TABLE dbo.Users ADD CONSTRAINT DF_Users_role DEFAULT 'viewer' FOR role;
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_Users_role')
    ALTER TABLE dbo.Users ADD CONSTRAINT CK_Users_role CHECK (role IN ('admin', 'manager', 'viewer'));
GO
