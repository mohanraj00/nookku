"""The toy shop agent of the tests as an entry. It speaks the agent contract with serve()."""

from toy_agent import shop_reply

from verbatim_relay.agent import serve

serve(lambda message, history: shop_reply(message))
