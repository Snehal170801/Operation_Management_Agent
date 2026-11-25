-- One purchase order per case, created automatically once a vendor selection is approved.

IF OBJECT_ID('dbo.PurchaseOrders', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.PurchaseOrders (
        purchase_order_id       UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        -- Human-facing number: PO-<po_number>.
        po_number               INT              IDENTITY(1001, 1) NOT NULL UNIQUE,
        case_id                 UNIQUEIDENTIFIER NOT NULL UNIQUE FOREIGN KEY REFERENCES dbo.Cases(case_id),
        vendor_id               UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Vendors(vendor_id),
        total_amount            DECIMAL(12,2)    NULL,
        lead_time_days          INT              NULL,
        terms                   NVARCHAR(500)    NULL,
        expected_delivery_date  DATE             NULL,
        items_json              NVARCHAR(MAX)    NOT NULL,
        -- issued (created, not yet emailed) | sent | send_failed
        status                  NVARCHAR(20)     NOT NULL DEFAULT 'issued',
        created_at              DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        sent_at                 DATETIME2        NULL
    );
END
GO
