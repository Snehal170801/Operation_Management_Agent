-- Approvals that sit unanswered get reminders; track how many have gone out and when.

IF COL_LENGTH('dbo.Approvals', 'reminder_count') IS NULL
    ALTER TABLE dbo.Approvals ADD reminder_count INT NOT NULL CONSTRAINT DF_Approvals_reminder_count DEFAULT 0;
GO

IF COL_LENGTH('dbo.Approvals', 'last_reminded_at') IS NULL
    ALTER TABLE dbo.Approvals ADD last_reminded_at DATETIME2 NULL;
GO
