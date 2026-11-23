// Keep filter changes and page resets atomic, including rapid navigation.
export function transactionListReducer(state, action) {
  if (action.type === 'filter') return { type: action.value, page: 0 };
  if (action.type === 'page') return { ...state,
    page: typeof action.value === 'function' ? action.value(state.page) : action.value };
  return state;
}
