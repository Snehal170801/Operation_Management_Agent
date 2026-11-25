-- Vendor invoices, matched against the purchase order and the goods receipt.

IF OBJECT_ID('dbo.Invoices', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Invoices (
        invoice_id          UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        case_id             UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Cases(case_id),
        purchase_order_id   UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.PurchaseOrders(purchase_order_id),
        vendor_id           UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Vendors(vendor_id),
        invoice_number      NVARCHAR(100)    NULL,
        total_amount        DECIMAL(12,2)    NULL,
        raw_text            NVARCHAR(MAX)    NOT NULL,
        extracted_json      NVARCHAR(MAX)    NULL,
        -- matched | on_hold (waiting for goods receipt) | mismatch (needs a person) | approved | rejected
        status              NVARCHAR(20)     NOT NULL,
        issues              NVARCHAR(MAX)    NULL,   -- JSON array of plain-language problems
        source              NVARCHAR(20)     NOT NULL DEFAULT 'email',   -- email | manual
        decided_by          NVARCHAR(255)    NULL,
        decision_note       NVARCHAR(MAX)    NULL,
        created_at          DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        decided_at          DATETIME2        NULL
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Invoices_case_id')
    CREATE INDEX IX_Invoices_case_id ON dbo.Invoices(case_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Invoices_status')
    CREATE INDEX IX_Invoices_status ON dbo.Invoices(status);
GO

-- A vendor invoice number can only be live (matched / on hold / approved) once: the duplicate-payment
-- guard. Duplicates are still recorded, as mismatches, and rejected invoices free the number again.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_Invoices_vendor_number')
    CREATE UNIQUE INDEX UX_Invoices_vendor_number ON dbo.Invoices(vendor_id, invoice_number)
        WHERE invoice_number IS NOT NULL AND status IN ('matched', 'on_hold', 'approved');
GO
