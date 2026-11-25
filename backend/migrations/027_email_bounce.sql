-- A supplier whose email address is known not to work (the mail server bounced our email).

IF COL_LENGTH('dbo.Vendors', 'email_bounced_at') IS NULL
    ALTER TABLE dbo.Vendors ADD email_bounced_at DATETIME2 NULL;
GO

IF COL_LENGTH('dbo.Vendors', 'email_bounce_reason') IS NULL
    ALTER TABLE dbo.Vendors ADD email_bounce_reason NVARCHAR(300) NULL;
GO
