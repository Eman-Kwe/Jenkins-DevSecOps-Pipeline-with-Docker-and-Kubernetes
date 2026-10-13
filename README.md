# Infrastructure as Code with Terraform: Secure Azure Network

**Author:** Manuel Yannick Armah · **Based on:** Lab 04, Infrastructure as Code with Terraform, by Jhante Charles

## Project Overview

This project replaces manual Azure portal clicks with Terraform code. Instead of describing how to build a network step by step, a configuration file describes what the end state should look like, and Terraform works out the steps.

It deploys a resource group, virtual network, subnet, and a network security group (NSG) that allows HTTPS only and is attached to the subnet. A Checkov scan runs before anything is deployed, and `terraform destroy` removes everything at the end.

It builds on the base lab credited above. The base lab provides the resource group, VNet, subnet, and the Terraform workflow. The NSG rules, subnet association, tags, variables, comments, and Checkov scan are my additions.

> Personal lab project, not a production deployment.

**Skills demonstrated:**

- Declarative infrastructure in HashiCorp Configuration Language (HCL)
- The core Terraform workflow: `init`, `validate`, `plan`, `apply`, `destroy`
- Terraform state (`terraform.tfstate`) as the record of what exists
- Resource dependencies, resolved automatically (resource group, then VNet, then subnet)
- Network security: HTTPS-only inbound, explicit deny rule, NSG attached to a subnet
- Static security scanning of infrastructure code with Checkov
- Azure Cloud Shell as a zero-install environment

## Project Structure

```
azure-terraform-network/
├── README.md
├── architecture.svg
├── architecture.drawio
├── main.tf
├── variables.tf
├── .gitignore
├── .terraform.lock.hcl
└── screenshots/
```

## Architecture Diagram

![Architecture diagram](architecture.svg)

The editable version is [`architecture.drawio`](architecture.drawio). Open it at [app.diagrams.net](https://app.diagrams.net).

**How it works:** `main.tf` and `variables.tf` describe the desired network. `terraform init` downloads the Azure provider plugin, `terraform validate` checks the code is syntactically valid, `terraform plan` compares the code against the state file and previews what will change, and `terraform apply` makes the changes through the Azure Resource Manager API. Checkov scans the code before deployment.

## Prerequisites

- An active Azure subscription
- Access to the Azure portal. Nothing to install locally, because everything runs in Azure Cloud Shell (Bash).

## Naming Conventions Used

| Resource | Value |
|---|---|
| Resource group | `rg-lab04-tf-manuel` |
| Virtual network | `vnet-terraform` (`10.0.0.0/16`) |
| Subnet | `snet-backend` (`10.0.1.0/24`) |
| Network security group | `nsg-web` |
| Location | East US |
| Tags | `project = lab04`, `owner = manuel`, `env = lab` |

## What I Changed from the Base Lab

The base lab creates an NSG with no rules that isn't attached to anything, so it protects nothing. My changes:

- **NSG rules.** Allow HTTPS (443) and an explicit deny-all inbound rule.
- **NSG-to-subnet association.** `azurerm_subnet_network_security_group_association`, so the rules apply.
- **Tags** on the resource group, VNet, and NSG.
- **Variables.** Location, resource group name, address space, subnet prefix, and tags live in `variables.tf`.
- **Comments** on every block so the code reads without the lab open.
- **Checkov scan** before deploying.
- **Version constraint note.** `~> 3.0` allows 3.x releases and blocks 4.0. The lab describes it as "3.0 upward," which is not accurate.

## Project Steps

> Each **Screenshot** note says what to capture. Save the images in `screenshots/` with the filename shown, then delete the note. Take all screenshots **before Step 10**, because destroy removes the portal views. Blur your subscription ID and email address before saving portal screenshots.

### Step 1: Open Cloud Shell and Create the Project Folder

1. Sign in at portal.azure.com and open Cloud Shell (the `>_` icon, top-right toolbar).
2. Confirm the dropdown says **Bash**, not PowerShell.
3. Create and enter the folder:

```bash
mkdir terraform-lab
cd terraform-lab
```

### Step 2: Write the Terraform Configuration

Open the editor for each file, paste the contents from this repo, save with `Ctrl + S`, and close with `Ctrl + Q`:

```bash
code main.tf
code variables.tf
```

- [`main.tf`](main.tf): provider, resource group, VNet, subnet, NSG with two rules, and the NSG-to-subnet association
- [`variables.tf`](variables.tf): location, resource group name, address space, subnet prefix, tags

Confirm both files saved:

```bash
ls
cat main.tf
```

The file must be named `variables.tf`, not `variable.tf`.

### Step 3: Initialize Terraform

```bash
terraform init
```

This downloads the azurerm provider into a hidden `.terraform` folder and creates `.terraform.lock.hcl`, which locks the provider version. Look for:

```
Terraform has been successfully initialized!
```

> **Screenshot:** the init output showing the azurerm version and the success line.

![01 terraform init](screenshots/01-terraform-init.png)

### Step 4: Format and Validate

```bash
terraform fmt
terraform validate
```

Look for `Success! The configuration is valid.` Errors name the file and line.

### Step 5: Scan with Checkov

Checkov is an open-source tool that scans infrastructure code for security misconfigurations before anything is deployed. It reads the Terraform files, checks each resource against its built-in security rules, and reports pass or fail for every rule that applies.

> **Why it's necessary:** A misconfiguration caught in the code costs one edit. The same mistake found after deployment can mean an exposed port, a redeployment, or an incident. Scanning before `apply` catches problems like open SSH or RDP while nothing is live, and it gives you a repeatable check that can later run automatically in a pipeline.

Run the scan before deploying:

```bash
pip install checkov --user
export PATH=$PATH:~/.local/bin
checkov -d .
```

Look for `Passed checks: 7, Failed checks: 0, Skipped checks: 0`. See [Results](#results) for what each check means.

> **Screenshot:** the summary line and the list of passed checks (scroll or use `checkov -d . | tail -50` to fit them).

![02 checkov results](screenshots/02-checkov-results.png)

### Step 6: Preview the Plan

```bash
terraform plan
```

A read-only comparison of the code against the current state of Azure. Nothing is created yet. Look for:

```
Plan: 5 to add, 0 to change, 0 to destroy.
```

The five resources are the resource group, VNet, subnet, NSG, and association. A result of `3 to add` means the NSG and association blocks are missing from `main.tf`.

> **Screenshot:** the end of the plan output with the `Plan: 5 to add` line visible.

![03 terraform plan](screenshots/03-terraform-plan-5-to-add.png)

### Step 7: Apply the Configuration

```bash
terraform apply
```

Type the full word `yes`. Terraform creates the resource group first, then the VNet, then the subnet and NSG, then the association. Look for:

```
Apply complete! Resources: 5 added, 0 changed, 0 destroyed.
```

> **Screenshot:** the `Apply complete!` line with a few `Creation complete` lines above it.

![04 terraform apply](screenshots/04-terraform-apply-5-added.png)

### Step 8: Confirm the State File Exists

```bash
ls -la
terraform state list
```

`terraform.tfstate` is Terraform's record of what it created. It holds resource and subscription IDs, so **do not `cat` it on screen** and never commit it to GitHub. `terraform state list` shows the five tracked resources without exposing the contents.

> **Screenshot:** the `ls -la` output showing `terraform.tfstate`, plus the `terraform state list` output.

![05 state file](screenshots/05-state-file-ls.png)

### Step 9: Verify in the Azure Portal

Open the resource group `rg-lab04-tf-manuel` and check:

| Check | Where to look | What should be visible |
|---|---|---|
| Resources exist | Resource group > Overview | `vnet-terraform` and `nsg-web` |
| NSG is attached | `vnet-terraform` > Subnets | `snet-backend`, `10.0.1.0/24`, Security group = `nsg-web` |
| Rules are correct | `nsg-web` > Inbound security rules | `allow-https-inbound` (100) and `deny-all-inbound` (4096) |
| Tags applied | Resource group > Tags | `project`, `owner`, `env` |

> **Screenshots:** one per check. The subnet screenshot matters most, because it shows the NSG is protecting something.

![06 resource group](screenshots/06-portal-resource-group.png)
![07 subnet with NSG](screenshots/07-portal-subnet-nsg.png)
![08 NSG rules](screenshots/08-portal-nsg-rules.png)
![09 tags](screenshots/09-portal-tags.png)

### Step 10: Destroy the Environment

```bash
terraform destroy
```

Review the destruction plan, type `yes`, and look for:

```
Destroy complete! Resources: 5 destroyed.
```

Then open **Resource groups** in the portal and confirm `rg-lab04-tf-manuel` is gone. Use `terraform destroy` instead of deleting in the portal, so the state file stays in sync with Azure.

> **Screenshots:** the `Destroy complete!` line, and the Resource groups list without `rg-lab04-tf-manuel`.

![10 terraform destroy](screenshots/10-terraform-destroy-5-destroyed.png)
![11 resource group gone](screenshots/11-portal-rg-gone.png)

## Results

**Checkov v3.3.23: 7 passed, 0 failed, 0 skipped**

| Check | What it confirms | Resource |
|---|---|---|
| `CKV_AZURE_10` | SSH is not open to the internet | `nsg-web` |
| `CKV_AZURE_9` | RDP is not open to the internet | `nsg-web` |
| `CKV_AZURE_77` | UDP services are not open to the internet | `nsg-web` |
| `CKV_AZURE_160` | HTTP (port 80) is not open to the internet | `nsg-web` |
| `CKV2_AZURE_31` | Subnet has an NSG attached | `snet-backend` |
| `CKV_AZURE_183` | VNet uses local DNS addresses | `vnet-terraform` |
| `CKV_AZURE_182` | VNet has at least 2 connected DNS endpoints | `vnet-terraform` |

A clean scan on this small project does not mean the environment is secure. There are no VMs, storage, or databases yet, so only seven rules applied, and Checkov reads the code rather than the live resources.

## Security Decisions

- **HTTPS only (443).** Port 80 stays closed because it is unencrypted.
- **Explicit deny-all rule.** Azure already denies inbound traffic by default. Writing the rule out makes the intent visible and easy to audit.
- **NSG attached to the subnet.** An NSG does nothing until it is associated with something. Checkov verifies this with `CKV2_AZURE_31`.
- **Tags.** Not a security control. They show ownership and purpose for cost tracking, cleanup, and audits.
- **State stays out of Git.** `.gitignore` excludes `terraform.tfstate`. `.terraform.lock.hcl` is committed so the provider version stays consistent.

## Troubleshooting / Common Issues

| Issue | Cause | Fix |
|---|---|---|
| `Resource Group already exists` | A group with this name exists from an earlier attempt or was created manually | Change `rg_name` in `variables.tf`, or delete the existing group in the portal first |
| `terraform: command not found` | Cloud Shell session without Terraform loaded | Close and reopen Cloud Shell. Terraform is pre-installed in new sessions |
| Syntax error on a line | Missing `}` or `"`, or a stray character from pasting | Run `code main.tf`, go to the line in the error, and check every `{` has a matching `}` |
| `Plan: 3 to add` instead of 5 | NSG or association block missing from `main.tf` | Run `grep -n "azurerm_network_security_group" main.tf` and add the missing blocks |
| `Duplicate resource` error | The lab's empty NSG block was pasted in addition to the one with rules | Keep only one `azurerm_network_security_group "nsg"` block |
| `checkov: command not found` | `~/.local/bin` is not on the PATH | Run `export PATH=$PATH:~/.local/bin`, or `~/.local/bin/checkov -d .` |
| `apply` fails partway through | Transient Azure API error or quota limit | Run `terraform apply` again. Terraform skips what exists and retries what failed |
| Editor won't close with `Ctrl + Q` | Browser intercepts the shortcut | Click the X in the top-right of the editor panel |

## Cleanup

`terraform destroy` in Step 10 removes every resource in one command and keeps the state file in sync with Azure. Nothing is deleted manually through the portal, because that would leave `terraform.tfstate` pointing at resources that no longer exist.

## Key Takeaways

- **Infrastructure as Code describes the destination.** The configuration says what should exist, and Terraform works out how to get there, including the dependency order.
- **The state file makes incremental changes possible.** Without `terraform.tfstate`, Terraform could not tell what already exists from what needs to be created.
- **An NSG that isn't attached protects nothing.** The base lab's NSG had no rules and no association. The association block is what makes the rules apply.
- **Scan before you deploy.** Checkov catches misconfigurations when fixing them costs one edit instead of a redeployment.
- **`destroy` is the correct cleanup.** It keeps the state file and Azure in sync, and it avoids leftover resources and charges.

---

**Difficulty:** Intermediate | **Time to complete:** about 1 to 2 hours including the extensions
