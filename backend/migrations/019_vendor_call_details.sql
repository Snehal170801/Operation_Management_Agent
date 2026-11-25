-- Vendors can be phoned after we email them: a phone number and the language to speak.

IF COL_LENGTH('dbo.Vendors', 'phone') IS NULL
    ALTER TABLE dbo.Vendors ADD phone NVARCHAR(20) NULL;       -- +country-code form, e.g. +919876543210
GO

IF COL_LENGTH('dbo.Vendors', 'call_language') IS NULL
    ALTER TABLE dbo.Vendors ADD call_language NVARCHAR(5) NOT NULL CONSTRAINT DF_Vendors_call_language DEFAULT 'hi';  -- hi | mr | en
GO
