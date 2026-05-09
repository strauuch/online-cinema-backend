class StubEmailSender:
    async def send_activation_email(self, *args, **kwargs):
        pass

    async def send_activation_complete_email(self, *args, **kwargs):
        pass

    async def send_password_reset_email(self, *args, **kwargs):
        pass

    async def send_password_reset_complete_email(self, *args, **kwargs):
        pass

    async def send_order_confirmation_email(self, *args, **kwargs):
        pass