-- Stock items: a unit (pcs, kg, box...), a category, and an optional preferred supplier.

IF COL_LENGTH('dbo.Stock', 'unit') IS NULL
    ALTER TABLE dbo.Stock ADD unit NVARCHAR(30) NULL;
GO

IF COL_LENGTH('dbo.Stock', 'category') IS NULL
    ALTER TABLE dbo.Stock ADD category NVARCHAR(60) NULL;
GO

-- The supplier that is always asked for a quote when a request includes this item. Not a foreign key: suppliers are never deleted,
-- and the application checks the supplier exists when it is chosen.
IF COL_LENGTH('dbo.Stock', 'preferred_vendor_id') IS NULL
    ALTER TABLE dbo.Stock ADD preferred_vendor_id UNIQUEIDENTIFIER NULL;
GO
