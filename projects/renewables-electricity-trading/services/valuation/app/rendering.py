from decimal import Decimal
from rest_framework.renderers import JSONRenderer
from rest_framework.utils.encoders import JSONEncoder


class FinancialEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


class FinancialRenderer(JSONRenderer):
    encoder_class = FinancialEncoder
