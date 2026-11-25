-- Quotes can expire: when the supplier's price stops being valid.

IF COL_LENGTH('dbo.VendorQuotes', 'valid_until') IS NULL
    ALTER TABLE dbo.VendorQuotes ADD valid_until DATETIME2 NULL;
GO
