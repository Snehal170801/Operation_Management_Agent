-- The Store Room (read-only browser of all stored operational data) is a new permission.
-- Anyone who could already see every case keeps seeing everything, so they get it too.
-- Requesters (role `user`) do not hold cases:read_all and so do not get it.

INSERT INTO dbo.RolePermissions (role_id, permission)
SELECT rp.role_id, 'storeroom:read'
FROM dbo.RolePermissions rp
WHERE rp.permission = 'cases:read_all'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.RolePermissions x WHERE x.role_id = rp.role_id AND x.permission = 'storeroom:read'
  );
GO
