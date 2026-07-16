class MessageBuilder:
    def build(self, subject, body, **kwargs):
        return {"subject": subject, "body": body, **kwargs}
