-- Tax (GST) lines on purchase orders and invoices. Matching only: nothing here pays anything.
-- An order gets them when a tax rate is set in Settings -> Configure; an invoice records what the supplier showed.

IF COL_LENGTH('dbo.PurchaseOrders', 'tax_rate_pct') IS NULL
    ALTER TABLE dbo.PurchaseOrders ADD tax_rate_pct DECIMAL(5,2) NULL, tax_amount DECIMAL(18,2) NULL, total_with_tax DECIMAL(18,2) NULL;
GO

IF COL_LENGTH('dbo.Invoices', 'tax_rate_pct') IS NULL
    ALTER TABLE dbo.Invoices ADD subtotal DECIMAL(18,2) NULL, tax_rate_pct DECIMAL(5,2) NULL, tax_amount DECIMAL(18,2) NULL;
GO
