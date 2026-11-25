-- Automatic sourcing: vendors get an email address, and every quote request (RFQ)
-- sent for a case is tracked so the worker can chase silent vendors and know when to rank.

IF COL_LENGTH('dbo.Vendors', 'email') IS NULL
    ALTER TABLE dbo.Vendors ADD email NVARCHAR(255) NULL;
GO

IF OBJECT_ID('dbo.Rfqs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Rfqs (
        rfq_id              UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        case_id             UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Cases(case_id),
        vendor_id           UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Vendors(vendor_id),
        -- sent | replied
        status              NVARCHAR(20)     NOT NULL DEFAULT 'sent',
        sent_at             DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        last_contacted_at   DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        reminder_count      INT              NOT NULL DEFAULT 0,
        deadline_at         DATETIME2        NOT NULL,
        replied_at          DATETIME2        NULL,
        CONSTRAINT UQ_Rfqs_case_vendor UNIQUE (case_id, vendor_id)
    );
END
GO
