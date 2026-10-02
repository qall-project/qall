# Contribute to Qall

Qall is an open-source project backed by Scaleway's Quantum team and released under the Apache 2.0 license.

Contributions are welcome through GitHub, whether you want to report a bug, suggest an improvement, improve documentation, or contribute code.

## Topics

- [Reporting Security Issues](#reporting-security-issues)
- [Reporting Issues](#reporting-issues)
- [Suggesting a Feature](#suggesting-a-feature)
- [Contributing Code](#contributing-code)
- [Pull Request Guidelines](#pull-request-guidelines)
- [Community Guidelines](#community-guidelines)

## Reporting Security Issues

At Scaleway, we take security seriously.

If you find a security issue in Qall, please notify us by sending an email to [qall-project@scaleway.com](mailto:security@scaleway.com).

Please **do not create a GitHub issue** for security vulnerabilities.

We will follow up with you promptly with more information and a plan for remediation.

We currently do not offer a paid security bounty program, but we greatly appreciate your help in making Qall and the surrounding ecosystem more secure.

## Reporting Issues

Bug reports and detailed issue reports are valuable contributions to Qall.

Before opening a new issue, please check the existing issues to see whether a similar report already exists. If it does, add a 👍 reaction and provide any additional information that may help us investigate.

When reporting an issue, please include as much relevant information as possible, such as:

- Qall version or commit
- Python version
- Operating system
- How Qall was executed (for example, local or remote execution)
- Relevant workflow or task definition
- Steps to reproduce the issue
- Expected and actual behavior
- Relevant logs or error messages

For issues involving a specific execution backend or resource, please also provide the relevant resource and configuration when possible.

## Suggesting a Feature

We welcome ideas that can make Qall more useful for heterogeneous and hybrid computing.

When suggesting a feature, please consider:

- **What problem does it solve?**
- **Who benefits from it?**
- **What would the expected user experience look like?**
- **Could the feature be implemented in a provider- and infrastructure-agnostic way?**
- **How does it fit with Qall's execution model and goals?**

For larger changes, opening an issue first can be useful to discuss the design before starting implementation.

## Contributing Code

### Submit Code

To contribute code:

1. Fork the project.
2. Create a topic branch from the current `main` branch.
3. Make your changes.
4. Add or update tests covering the changes.
5. Update the documentation when relevant.
6. Run the relevant checks locally.
7. Push your commits to your fork.
8. Open a pull request against the `main` branch.

Keep changes focused and avoid combining unrelated changes in the same pull request.

For larger architectural changes, we recommend discussing the approach in an issue before implementation.

### Pull Request Guidelines

The goal of the pull request process is to make changes easy to review, understand and maintain.

Please:

- **Use a clear pull request title** describing what is being changed.
- **Keep pull requests focused** on a specific change or problem.
- **Include tests** for new or modified behavior.
- **Update documentation** when the change affects user-facing behavior or architecture.
- **Keep the implementation readable** and avoid unnecessary complexity.
- **Explain design decisions** when they are not obvious from the code.
- **Mark work-in-progress pull requests** with `[WIP]` when they are not ready for review.
- **Keep the pull request up to date** with the current `main` branch.

If you are addressing an existing issue, reference it from the pull request description.

Please do not merge `main` into your topic branch. Rebase your branch when necessary to keep it up to date.

Maintainers may request changes, ask for additional tests or documentation, or suggest alternative approaches before merging.

## Development Principles

Qall is designed around a few principles that are particularly relevant when contributing:

- **Infrastructure agnostic**: avoid coupling the core execution model to a specific provider or infrastructure.
- **Clear separation of concerns**: keep the SDK, execution logic, registry, daemon and backend integrations separated.
- **Composable execution**: changes should preserve the ability to combine heterogeneous compute resources in a single workflow.
- **Developer experience**: Qall should make hybrid workloads easier to define, evolve and execute.
- **Open interfaces**: prefer well-defined interfaces and abstractions that can be implemented by different infrastructure providers.

When adding a new capability, consider whether it belongs in the core execution model or in a provider-, backend- or infrastructure-specific component.

## Community Guidelines

Please be respectful and constructive when participating in the Qall community.

Questions, discussions, ideas and constructive criticism are welcome. When proposing changes, focus on the problem being solved and help maintain a collaborative environment.

Thank you for contributing to **Qall**!