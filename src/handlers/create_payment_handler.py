"""
Handler: create payment transaction
SPDX - License - Identifier: LGPL - 3.0 - or -later
Auteurs : Gabriel C. Ullmann, Fabio Petrillo, 2025
"""
import config
import requests
from handlers.handler import Handler
from order_saga_state import OrderSagaState

class CreatePaymentHandler(Handler):
    """ Handle the creation of a payment transaction for a given order. Trigger rollback of previous steps in case of failure. """

    def __init__(self, order_id, order_data):
        """ Constructor method """
        self.order_id = order_id
        self.order_data = order_data
        self.total_amount = 0
        super().__init__()

    def run(self):
        """Call payment microservice to generate payment transaction"""
        try:
            # 1) On récupère la commande dans le Store Manager pour connaître son total_amount,
            #    qui servira de montant de la transaction de paiement.
            order_response = requests.get(
                f'{config.API_GATEWAY_URL}/store-manager-api/orders/{self.order_id}',
                headers={'Content-Type': 'application/json'}
            )
            if not order_response.ok:
                self.logger.error(f"GetOrder a échoué : {order_response.status_code} - {order_response.text}")
                return self.rollback()

            order = order_response.json() or {}
            self.total_amount = order.get('total_amount', 0)

            # 2) On crée la transaction de paiement via l'API Payments (à travers la Gateway).
            payment_response = requests.post(
                f'{config.API_GATEWAY_URL}/payments-api/payments',
                json={
                    "user_id": self.order_data.get('user_id'),
                    "order_id": self.order_id,
                    "total_amount": self.total_amount
                },
                headers={'Content-Type': 'application/json'}
            )

            if payment_response.ok:
                self.logger.debug("Transition d'état: CreatePayment -> PAYMENT_CREATED")
                return OrderSagaState.PAYMENT_CREATED
            else:
                self.logger.error(f"CreatePayment a échoué : {payment_response.status_code} - {payment_response.text}")
                return self.rollback()

        except Exception as e:
            self.logger.error("CreatePayment a échoué : " + str(e))
            return self.rollback()

    def rollback(self):
        """ Call StoreManager to restore stock quantities if payment transaction creation fails """
        # Compensation : le stock avait été retiré à l'étape précédente. On remet en stock
        # (opération "+") tous les articles de la commande pour annuler ce retrait.
        try:
            requests.put(f'{config.API_GATEWAY_URL}/store-manager-api/stocks',
                json={
                    "items": self.order_data.get('items', []),
                    "operation": "+"
                },
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            # Pas de rollback sur les rollbacks : on journalise et on poursuit vers l'état suivant.
            self.logger.error("Compensation CreatePayment (restauration stock) a échoué : " + str(e))

        self.logger.debug("Transition d'état: CreatePaymentFailure -> STOCK_INCREASED")
        return OrderSagaState.STOCK_INCREASED
