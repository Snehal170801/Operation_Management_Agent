-- Sending a request back out for new quotes after an approver rejects the offers.
-- The earlier round's quotes are kept for the record but stop counting: superseded_at marks them.

IF COL_LENGTH('dbo.VendorQuotes', 'superseded_at') IS NULL
    ALTER TABLE dbo.VendorQuotes ADD superseded_at DATETIME2 NULL;
GO
