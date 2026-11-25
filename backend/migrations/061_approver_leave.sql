-- Approver leave and a backup approver (delegate). While a person is on leave, approvals that would be sent to them go to their delegate
-- instead (and to the admins if there is none). Dates are calendar days (India time); leave the dates empty for "not on leave".

IF COL_LENGTH('dbo.Users', 'on_leave_from') IS NULL
    ALTER TABLE dbo.Users ADD on_leave_from DATE NULL;
GO

IF COL_LENGTH('dbo.Users', 'on_leave_until') IS NULL
    ALTER TABLE dbo.Users ADD on_leave_until DATE NULL;
GO

IF COL_LENGTH('dbo.Users', 'delegate_user_id') IS NULL
    ALTER TABLE dbo.Users ADD delegate_user_id UNIQUEIDENTIFIER NULL;     -- no foreign key: a deleted delegate simply stops counting
GO
