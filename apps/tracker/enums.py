from django.db import models

class QualityLevel(models.TextChoices):
    STANDARD = "standard", "Standard (1.0x)"
    STRONG = "strong", "Strong (1.5x)"
    HIGH = "high", "High (2.0x)"
    EXCEPTIONAL = "exceptional", "Exceptional (3.0x)"

QUALITY_MULTIPLIERS = {
    QualityLevel.STANDARD: 1.0,
    QualityLevel.STRONG: 1.5,
    QualityLevel.HIGH: 2.0,
    QualityLevel.EXCEPTIONAL: 3.0,
}

class MaeBlock(models.TextChoices):
    MORNING = "morning", "Morning"
    AFTERNOON = "afternoon", "Afternoon"
    EVENING = "evening", "Evening"
