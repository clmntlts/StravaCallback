// Use dynamic import() for node-fetch
export default async function handler(req, res) {
    if (req.method === 'POST') {
        const { code } = req.body;

        if (!code) {
            return res.status(400).json({ success: false, message: 'Authorization code is required' });
        }

        const fetch = (await import('node-fetch')).default;

        const webhookUrl = process.env.BOTPRESS_WEBHOOK_URL;
        const clientId = process.env.STRAVA_CLIENT_ID;
        const clientSecret = process.env.STRAVA_CLIENT_SECRET;

        if (!webhookUrl || !clientId || !clientSecret) {
            return res.status(500).json({ success: false, message: 'Missing environment variables' });
        }

        const payload = {
            code,
            client_id: clientId,
            client_secret: clientSecret,
            conversationId: 'conv_01J82KZJG68G6GZXM1AJTZGEDC'
        };

        try {
            const response = await fetch(webhookUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            res.status(200).json({ success: true, data });
        } catch (error) {
            res.status(500).json({ success: false, message: 'Failed to send POST request to webhook', error });
        }
    } else {
        res.status(405).json({ success: false, message: 'Method not allowed' });
    }
}
