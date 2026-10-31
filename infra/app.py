#!/usr/bin/env python3
"""CDK entry point. Deploy with:  cd infra && cdk deploy"""

import aws_cdk as cdk

from reviewbot_stack import ReviewBotStack

app = cdk.App()
ReviewBotStack(app, "ReviewBotStack")
app.synth()
