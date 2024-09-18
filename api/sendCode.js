// Use dynamic import() for node-fetch
export default async function handler(req, res) {
    if (req.method === 'POST') {
        const { code } = req.body;

        if (!code) {
            return res.status(400).json({ success: false, message: 'Authorization code is required' });
        }

        try {
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
            };

            const response = await fetch(webhookUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }

            const data = await response.json();
            res.status(200).json({ success: true, data });
        } catch (error) {
            console.error('Error:', error); // Log the error to the server logs
            res.status(500).json({ success: false, message: 'Failed to send POST request to webhook', error: error.message });
        }
    } else {
        res.status(405).json({ success: false, message: 'Method not allowed' });
    }
}
