"""Sample stock for testing. Descriptions are kept short and singular because the stock check matches
a request line to a stock row by its exact description (case-insensitive): "Laptop" matches
"laptop" but not "laptops" or "Dell laptop".

Quantities are deliberately mixed so every path gets exercised:
  * plenty    -> a normal request is fulfilled straight from stock
  * low       -> a bigger request is NOT covered and goes out to suppliers
  * zero      -> always goes to suppliers
"""

STOCK: tuple[tuple[str, int], ...] = (
    # IT
    ("Laptop", 100),
    ("Desktop computer", 40),
    ("Monitor 24 inch", 60),
    ("Monitor 27 inch", 25),
    ("Keyboard", 150),
    ("Mouse", 150),
    ("Webcam", 30),
    ("Headset", 45),
    ("Printer", 12),
    ("External hard disk 1TB", 35),
    ("Wi-Fi router", 18),
    ("Network switch 24 port", 6),
    ("UPS 1 kVA", 10),
    # Mobiles & tablets
    ("Tablet", 30),
    ("Mobile phone", 25),
    ("Mobile charger", 80),
    # Appliances & facilities
    ("Air conditioner 1.5 ton", 8),
    ("Ceiling fan", 50),
    ("Table fan", 20),
    ("Water dispenser", 5),
    ("Refrigerator", 3),
    ("Microwave oven", 4),
    ("LED bulb", 300),
    # Security
    ("CCTV camera", 20),
    ("NVR 16 channel", 0),
    ("Biometric attendance device", 7),
    ("Door access controller", 9),
    # Furniture & office
    ("Office chair", 40),
    ("Office desk", 25),
    ("Whiteboard", 10),
    ("Projector", 4),
    ("A4 paper ream", 500),
    # Deliberately out of stock
    ("Server rack", 0),
    ("Jetson 16GB", 0),
)
