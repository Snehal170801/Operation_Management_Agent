
IF OBJECT_ID('dbo.Vendors', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Vendors (
        vendor_id           UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        name                NVARCHAR(255)    NOT NULL UNIQUE,
        reliability_score   DECIMAL(3,1)     NOT NULL DEFAULT 3.0,
        created_at          DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF OBJECT_ID('dbo.VendorQuotes', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.VendorQuotes (
        quote_id            UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        case_id             UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Cases(case_id),
        vendor_id           UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Vendors(vendor_id),
        raw_quote_text      NVARCHAR(MAX)    NOT NULL,
        price               DECIMAL(12,2)    NULL,
        lead_time_days      INT              NULL,
        terms               NVARCHAR(500)    NULL,
        created_at          DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF OBJECT_ID('dbo.VendorSelections', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.VendorSelections (
        case_id             UNIQUEIDENTIFIER NOT NULL PRIMARY KEY FOREIGN KEY REFERENCES dbo.Cases(case_id),
        vendor_id           UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Vendors(vendor_id),
        rationale           NVARCHAR(MAX)    NULL,
        created_at          DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_VendorQuotes_case_id')
BEGIN
    CREATE INDEX IX_VendorQuotes_case_id ON dbo.VendorQuotes(case_id);
END
GO
