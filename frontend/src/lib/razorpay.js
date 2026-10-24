// Loads Razorpay Checkout on demand (only the billing page needs it) and opens it for a server-created order.
let loading
export function loadCheckout() {
  if (window.Razorpay) return Promise.resolve(window.Razorpay)
  loading ||= new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = 'https://checkout.razorpay.com/v1/checkout.js'
    s.async = true
    s.onload = () => resolve(window.Razorpay)
    s.onerror = () => { loading = null; reject(new Error('Could not load the payment window. Check your connection or ad blocker and try again.')) }
    document.head.appendChild(s)
  })
  return loading
}

export async function openCheckout(order, { onPaid, onDismiss }) {
  const Razorpay = await loadCheckout()
  const rzp = new Razorpay({
    key: order.key_id, order_id: order.order_id, amount: order.amount, currency: order.currency,
    name: order.name, description: order.description, prefill: order.prefill, theme: { color: '#4f5bef' },
    handler: onPaid,
    modal: { ondismiss: onDismiss },
  })
  rzp.open()
}
