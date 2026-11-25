-- Returning faulty goods and waiting for a replacement or a credit note. Tracking only: nothing here pays or reduces anything owed.

IF COL_LENGTH('dbo.GoodsIssues', 'return_status') IS NULL
    ALTER TABLE dbo.GoodsIssues ADD return_status NVARCHAR(20) NULL, return_ref NVARCHAR(100) NULL, returned_at DATETIME2 NULL, returned_by NVARCHAR(255) NULL,
        replacement_status NVARCHAR(20) NULL, replacement_expected_at DATETIME2 NULL, replacement_received_at DATETIME2 NULL, credit_note_number NVARCHAR(100) NULL;
GO
