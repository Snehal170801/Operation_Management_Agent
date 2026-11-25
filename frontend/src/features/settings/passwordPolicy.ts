export const PASSWORD_HINT = 'At least 8 characters with an uppercase letter, a lowercase letter and a number.'

/** Client-side mirror of the server rules, for instant feedback. The server remains the authority. */
export function passwordProblems(password: string, username = ''): string[] {
  const problems: string[] = []
  if (password.length < 8) problems.push('At least 8 characters')
  if (!/[a-z]/.test(password)) problems.push('A lowercase letter')
  if (!/[A-Z]/.test(password)) problems.push('An uppercase letter')
  if (!/\d/.test(password)) problems.push('A number')
  if (username && password.toLowerCase().includes(username.toLowerCase())) problems.push("Doesn't contain your username")
  return problems
}
