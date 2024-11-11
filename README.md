This is an AWS CDK project to deploy components of the [GDI starter kit](
https://gdi.onemilliongenomes.eu/gdi-starter-kit.html) to AWS.

## Goal

The end goal is to be able to run `cdk deploy GdiStarterKitStack` and have all
all the services up and running. 

## Status

Currently, the following services are deployed:
 * REMS

## Prerequisites

### AAI

* An OIDC Provider (OP) — for example [LS-AAI](
  https://services.aai.lifescience-ri.eu/spreg/) or [Google Identity](
  https://console.cloud.google.com/apis/credentials) — configured with your
  service endpoints as RPs. You generally need to specify at least:
  * login URL
  * redirect URL
  * oAuth flow (e.g. PKCE)
  * scopes
  and take note of the generated `client-id` and `client-secret`

### AWS

* An AWS account with permissions to create resources
* An AWS Secrets Manager entry (type: other) describing the REMS OIDC RP config
  with 3 key-vals:
  - 'oidc-metadata-url'
  - 'oidc-client-id'
  - 'oidc-client-secret'
* An AWS Route 53 Hosted Zone record configured with your domain e.g. `my.org`

### Local CDK config

* AWS CDK v2 for Python installed
* The CDK `rems_oidc_sec_name` context variable set to the name of the Secrets
  Manager record containing the RP config
* The `hz_domain` context variable set to the HZ domain you want to deploy to
  e.g. `my.org`
* (optionally) the `rems_domain_prefix` context variable set to the domain
  prefix to generate the deployed public URL (login URL as configured in the
  OP). If not supplied this defaults to `rems` — e.g. the public URL will be
  `rems.my.org`

## Post-deployment

### REMS

The application is primarily [configured](https://github.com/CSCfi/rems/blob/master/docs/configuration.md) via the `config.edn` file.

Follow the steps documented [here](
https://github.com/GenomicDataInfrastructure/starter-kit-rems?tab=readme-ov-file#using-rems) to demo:

* Adding yourself as an Owner
* Creating API key and using it to update the application, e.g.:
* Adding test data
* Creating a robot user
* Getting GA4GH visas from the API (use https://jwt.io/ to inspect the returned JWT)

Follow the steps documented [here](https://github.com/CSCfi/rems/blob/master/manual/owner.md#how-to-add-resources-to-rems) to configure the application with your own Forms, Workflows, Resources etc.

