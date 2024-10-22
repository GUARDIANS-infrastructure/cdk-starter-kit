import aws_cdk as core
import aws_cdk.assertions as assertions

from gdi_starter_kit.gdi_starter_kit_stack import GdiStarterKitStack

# example tests. To run these tests, uncomment this file along with the example
# resource in gdi_starter_kit/gdi_starter_kit_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = GdiStarterKitStack(app, "gdi-starter-kit")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
